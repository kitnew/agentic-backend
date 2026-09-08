from __future__ import annotations

import asyncio
import base64
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import pytest
from control_plane.application.execution_materialization import (
    ExecutionMaterializationService,
)
from control_plane.bootstrap import create_app
from control_plane.domain.managed_resource_errors import ManagedResourceConflict
from control_plane.infrastructure.encryption import CredentialCipher
from control_plane.infrastructure.persistence.database import Database
from control_plane.infrastructure.persistence.models import (
    Credential as CredentialRow,
)
from control_plane.infrastructure.persistence.models import (
    CredentialVersion as CredentialVersionRow,
)
from control_plane.infrastructure.persistence.models import IdempotencyReplay
from control_plane.infrastructure.persistence.runtime_execution_snapshots import (
    SqlAlchemyExecutionSnapshotRepository,
)
from control_plane.settings import Settings
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

KEY = base64.b64encode(b"0" * 32).decode()
SECRET = "plaintext-secret-never-persist"
AUTH = {"Authorization": "Bearer management-token"}


def settings(
    database_url: str,
    actor: str = "management:alice",
    scopes: str = "resources:read,credentials:write",
) -> Settings:
    return Settings(
        database_url=database_url,
        control_plane_encryption_key=KEY,
        voice_agent_service_secret="voice-secret",
        backend_core_service_secret="backend-secret",
        control_plane_management_token="management-token",
        control_plane_management_actor=actor,
        control_plane_management_scopes=scopes,
    )


@asynccontextmanager
async def client_for(
    database_url: str,
    *,
    actor: str = "management:alice",
    scopes: str = "resources:read,credentials:write",
    raise_app_exceptions: bool = True,
) -> AsyncIterator[tuple[AsyncClient, Database]]:
    database = Database(database_url)
    app = create_app(settings(database_url, actor, scopes), database=database)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=raise_app_exceptions),
            base_url="http://test",
            headers=AUTH,
        ) as client:
            yield client, database
    finally:
        await database.close()


async def create(
    client: AsyncClient,
    name: str,
    scope: dict[str, str],
    *,
    secret: str = SECRET,
    key: str | None = None,
):
    return await client.post(
        "/management/v1/credentials",
        headers={"Idempotency-Key": key or f"create-{name}-{uuid4()}"},
        json={"scope": scope, "name": name, "secret": secret},
    )


async def counts(database: Database) -> tuple[int, int, int]:
    async with database.sessions() as session:
        values = tuple(
            int(value or 0)
            for value in (
                await session.scalar(select(func.count()).select_from(CredentialRow)),
                await session.scalar(
                    select(func.count()).select_from(CredentialVersionRow)
                ),
                await session.scalar(
                    select(func.count()).select_from(IdempotencyReplay)
                ),
            )
        )
    return values  # type: ignore[return-value]


@pytest.mark.asyncio
async def test_create_scopes_and_normal_reads_are_secret_free(
    migrated_database_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    async with client_for(migrated_database_url) as (client, database):
        platform = await create(client, "platform-key", {"type": "platform"})
        tenant = await create(
            client,
            "tenant-key",
            {"type": "tenant", "tenant_id": "tenant-1"},
            secret="tenant-secret-never-persist",
        )

        assert platform.status_code == tenant.status_code == 201
        assert set(platform.json()) == {
            "id",
            "scope",
            "name",
            "status",
            "active_secret_version",
            "created_at",
            "updated_at",
            "revoked_at",
        }
        assert platform.json()["scope"] == {"type": "platform"}
        assert tenant.json()["scope"] == {
            "type": "tenant",
            "tenant_id": "tenant-1",
        }
        assert platform.json()["active_secret_version"] == 1
        assert platform.headers["etag"].startswith('"')

        listed = await client.get("/management/v1/credentials")
        fetched = await client.get(
            f"/management/v1/credentials/{platform.json()['id']}"
        )
        filtered = await client.get(
            "/management/v1/credentials",
            params={"scope_type": "tenant", "tenant_id": "tenant-1"},
        )
        assert listed.status_code == fetched.status_code == filtered.status_code == 200
        assert len(listed.json()) == 2
        assert fetched.json() == platform.json()
        assert filtered.json() == [tenant.json()]

        serialized = listed.text + fetched.text + filtered.text
        for forbidden in (
            SECRET,
            "tenant-secret-never-persist",
            "ciphertext",
            "nonce",
            "key_id",
            "algorithm",
            "active_version_id",
            "generation",
        ):
            assert forbidden not in serialized

        async with database.sessions() as session:
            versions = (await session.scalars(select(CredentialVersionRow))).all()
            replays = (await session.scalars(select(IdempotencyReplay))).all()
            credentials = (await session.scalars(select(CredentialRow))).all()
        assert len(versions) == 2
        assert all(SECRET.encode() not in row.ciphertext for row in versions)
        assert {row.created_by for row in versions} == {"management:alice"}
        assert {row.created_by for row in credentials} == {"management:alice"}
        assert all(SECRET not in str(row.logical_result) for row in replays)
        assert SECRET not in caplog.text

        assert (
            await create(
                client,
                "bad-tenant",
                {"type": "tenant"},
            )
        ).status_code == 422
        assert (
            await create(
                client,
                "bad-platform",
                {"type": "platform", "tenant_id": "tenant-1"},
            )
        ).status_code == 422


@pytest.mark.asyncio
async def test_create_is_idempotent_secret_sensitive_and_principal_scoped(
    migrated_database_url: str,
) -> None:
    request = {"type": "tenant", "tenant_id": "tenant-1"}
    async with client_for(migrated_database_url) as (alice, database):
        first = await create(alice, "same", request, key="shared-key")
        replay = await create(alice, "same", request, key="shared-key")
        conflict = await create(
            alice,
            "same",
            request,
            secret="different-secret-never-log",
            key="shared-key",
        )

        assert first.status_code == replay.status_code == 201
        assert replay.json() == first.json()
        assert replay.headers["etag"] == first.headers["etag"]
        assert conflict.status_code == 409
        assert conflict.json()["code"] == "idempotency_key_reused"
        assert "different-secret-never-log" not in conflict.text
        assert await counts(database) == (1, 1, 1)

    async with client_for(migrated_database_url, actor="management:bob") as (
        bob,
        database,
    ):
        second_principal = await create(
            bob,
            "same-name-is-not-identity",
            {"type": "platform"},
            key="shared-key",
        )
        assert second_principal.status_code == 201
        assert await counts(database) == (2, 2, 2)


@pytest.mark.asyncio
async def test_rotate_is_immutable_retry_safe_and_preconditioned(
    migrated_database_url: str,
) -> None:
    async with client_for(migrated_database_url) as (client, database):
        created = await create(client, "rotate", {"type": "platform"})
        credential_id = created.json()["id"]
        original_etag = created.headers["etag"]
        async with database.sessions() as session:
            original = await session.scalar(select(CredentialVersionRow))
            assert original is not None
            original_envelope = (
                original.id,
                original.credential_id,
                original.version_number,
                original.key_id,
                original.algorithm,
                original.nonce,
                original.ciphertext,
                original.created_at,
                original.created_by,
            )

        headers = {"Idempotency-Key": "rotate-key", "If-Match": original_etag}
        first = await client.post(
            f"/management/v1/credentials/{credential_id}/rotate",
            headers=headers,
            json={"secret": "rotated-secret-never-log"},
        )
        replay = await client.post(
            f"/management/v1/credentials/{credential_id}/rotate",
            headers=headers,
            json={"secret": "rotated-secret-never-log"},
        )
        conflict = await client.post(
            f"/management/v1/credentials/{credential_id}/rotate",
            headers=headers,
            json={"secret": "changed-secret-never-log"},
        )
        stale = await client.post(
            f"/management/v1/credentials/{credential_id}/rotate",
            headers={"Idempotency-Key": "stale-key", "If-Match": original_etag},
            json={"secret": "third-secret"},
        )

        assert first.status_code == replay.status_code == 200
        assert first.json()["active_secret_version"] == 2
        assert replay.json() == first.json()
        assert conflict.status_code == 409
        assert "changed-secret-never-log" not in conflict.text
        assert stale.status_code == 412

        async with database.sessions() as session:
            versions = (
                await session.scalars(
                    select(CredentialVersionRow).order_by(
                        CredentialVersionRow.version_number
                    )
                )
            ).all()
        assert len(versions) == 2
        assert sum(row.retired_at is None for row in versions) == 1
        assert (
            versions[0].id,
            versions[0].credential_id,
            versions[0].version_number,
            versions[0].key_id,
            versions[0].algorithm,
            versions[0].nonce,
            versions[0].ciphertext,
            versions[0].created_at,
            versions[0].created_by,
        ) == original_envelope

        concurrent = await asyncio.gather(
            client.post(
                f"/management/v1/credentials/{credential_id}/rotate",
                headers={
                    "Idempotency-Key": "concurrent-a",
                    "If-Match": first.headers["etag"],
                },
                json={"secret": "concurrent-a"},
            ),
            client.post(
                f"/management/v1/credentials/{credential_id}/rotate",
                headers={
                    "Idempotency-Key": "concurrent-b",
                    "If-Match": first.headers["etag"],
                },
                json={"secret": "concurrent-b"},
            ),
        )
        assert sorted(value.status_code for value in concurrent) == [200, 412]
        async with database.sessions() as session:
            rows = (await session.scalars(select(CredentialVersionRow))).all()
            replays = (await session.scalars(select(IdempotencyReplay))).all()
        assert len(rows) == 3
        assert sum(row.retired_at is None for row in rows) == 1
        assert not any(
            secret in str(replay.logical_result)
            for replay in replays
            for secret in (
                "rotated-secret-never-log",
                "changed-secret-never-log",
                "concurrent-a",
                "concurrent-b",
            )
        )


@pytest.mark.asyncio
async def test_revoke_is_retry_safe_and_preserves_resource_history_and_references(
    migrated_database_url: str,
) -> None:
    async with client_for(migrated_database_url) as (client, database):
        created = await create(client, "revoke", {"type": "platform"})
        credential_id = created.json()["id"]
        async with database.sessions.begin() as session:
            await session.execute(
                text(
                    "INSERT INTO control_plane.provider_connections "
                    "(id, key, provider_kind, credential_id, connection_config, enabled, generation, created_by, updated_by) "
                    "VALUES (:id, 'reference-survives', 'test', :credential_id, '{}'::jsonb, false, 1, 'test', 'test')"
                ),
                {"id": uuid4(), "credential_id": UUID(credential_id)},
            )

        headers = {
            "Idempotency-Key": "revoke-key",
            "If-Match": created.headers["etag"],
        }
        first = await client.post(
            f"/management/v1/credentials/{credential_id}/revoke", headers=headers
        )
        replay = await client.post(
            f"/management/v1/credentials/{credential_id}/revoke", headers=headers
        )
        fetched = await client.get(f"/management/v1/credentials/{credential_id}")

        assert first.status_code == replay.status_code == fetched.status_code == 200
        assert first.json()["status"] == "revoked"
        assert first.json()["active_secret_version"] == 1
        assert replay.json() == first.json() == fetched.json()
        async with database.sessions() as session:
            assert (
                await session.scalar(
                    text("SELECT count(*) FROM control_plane.credential_versions")
                )
                == 1
            )
            assert (
                await session.scalar(
                    text("SELECT count(*) FROM control_plane.provider_connections")
                )
                == 1
            )
            assert (
                await session.scalar(
                    text(
                        "SELECT revoked_by FROM control_plane.credentials WHERE id=:id"
                    ),
                    {"id": UUID(credential_id)},
                )
                == "management:alice"
            )

        rotate = await client.post(
            f"/management/v1/credentials/{credential_id}/rotate",
            headers={
                "Idempotency-Key": "after-revoke",
                "If-Match": first.headers["etag"],
            },
            json={"secret": "must-not-persist"},
        )
        assert rotate.status_code == 409
        assert "must-not-persist" not in rotate.text


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "rotate", "revoke"])
async def test_replay_failure_rolls_back_credential_mutation(
    migrated_database_url: str, operation: str
) -> None:
    async with client_for(migrated_database_url, raise_app_exceptions=False) as (
        client,
        database,
    ):
        created = None
        if operation != "create":
            created = await create(client, operation, {"type": "platform"})
        before = await counts(database)
        async with database.sessions.begin() as session:
            await session.execute(
                text(
                    "CREATE FUNCTION control_plane.fail_replay_insert() RETURNS trigger "
                    "LANGUAGE plpgsql AS 'BEGIN RAISE EXCEPTION ''replay insert failed''; END'"
                )
            )
            await session.execute(
                text(
                    "CREATE TRIGGER fail_replay_insert BEFORE INSERT ON "
                    "control_plane.idempotency_replays FOR EACH ROW "
                    "EXECUTE FUNCTION control_plane.fail_replay_insert()"
                )
            )

        if operation == "create":
            response = await create(
                client,
                "failed-create",
                {"type": "platform"},
                key="failed-create",
            )
        elif operation == "rotate":
            assert created is not None
            response = await client.post(
                f"/management/v1/credentials/{created.json()['id']}/rotate",
                headers={
                    "Idempotency-Key": "failed-rotate",
                    "If-Match": created.headers["etag"],
                },
                json={"secret": "failed-rotation-secret"},
            )
        else:
            assert created is not None
            response = await client.post(
                f"/management/v1/credentials/{created.json()['id']}/revoke",
                headers={
                    "Idempotency-Key": "failed-revoke",
                    "If-Match": created.headers["etag"],
                },
            )

        assert response.status_code == 500
        assert await counts(database) == before
        if created is not None:
            fetched = await client.get(
                f"/management/v1/credentials/{created.json()['id']}"
            )
            assert fetched.json()["status"] == "active"
            assert fetched.json()["active_secret_version"] == 1


@pytest.mark.asyncio
async def test_mutation_failure_creates_no_replay_and_preserves_active_version(
    migrated_database_url: str,
) -> None:
    async with client_for(migrated_database_url, raise_app_exceptions=False) as (
        client,
        database,
    ):
        created = await create(client, "mutation-failure", {"type": "platform"})
        async with database.sessions.begin() as session:
            await session.execute(
                text(
                    "CREATE FUNCTION control_plane.fail_version_insert() RETURNS trigger "
                    "LANGUAGE plpgsql AS 'BEGIN RAISE EXCEPTION ''version insert failed''; END'"
                )
            )
            await session.execute(
                text(
                    "CREATE TRIGGER fail_version_insert BEFORE INSERT ON "
                    "control_plane.credential_versions FOR EACH ROW "
                    "EXECUTE FUNCTION control_plane.fail_version_insert()"
                )
            )
        response = await client.post(
            f"/management/v1/credentials/{created.json()['id']}/rotate",
            headers={
                "Idempotency-Key": "mutation-failed",
                "If-Match": created.headers["etag"],
            },
            json={"secret": "mutation-failed-secret"},
        )
        assert response.status_code == 500
        assert await counts(database) == (1, 1, 1)
        fetched = await client.get(f"/management/v1/credentials/{created.json()['id']}")
        assert fetched.json()["active_secret_version"] == 1


@pytest.mark.asyncio
async def test_create_mutation_failure_leaves_no_partial_state(
    migrated_database_url: str,
) -> None:
    async with client_for(migrated_database_url, raise_app_exceptions=False) as (
        client,
        database,
    ):
        async with database.sessions.begin() as session:
            await session.execute(
                text(
                    "CREATE FUNCTION control_plane.fail_version_insert() RETURNS trigger "
                    "LANGUAGE plpgsql AS 'BEGIN RAISE EXCEPTION ''version insert failed''; END'"
                )
            )
            await session.execute(
                text(
                    "CREATE TRIGGER fail_version_insert BEFORE INSERT ON "
                    "control_plane.credential_versions FOR EACH ROW "
                    "EXECUTE FUNCTION control_plane.fail_version_insert()"
                )
            )
        response = await create(
            client,
            "failed-before-version",
            {"type": "platform"},
            key="failed-before-version",
        )
        assert response.status_code == 500
        assert await counts(database) == (0, 0, 0)


@pytest.mark.asyncio
async def test_revoked_credential_cannot_materialize(
    migrated_database_url: str,
) -> None:
    async with client_for(migrated_database_url) as (client, database):
        created = await create(client, "materialize", {"type": "platform"})
        revoked = await client.post(
            f"/management/v1/credentials/{created.json()['id']}/revoke",
            headers={
                "Idempotency-Key": "revoke-materialize",
                "If-Match": created.headers["etag"],
            },
        )
        assert revoked.status_code == 200
        materializer = ExecutionMaterializationService(
            database.sessions,
            CredentialCipher(KEY),
            SqlAlchemyExecutionSnapshotRepository(database.sessions),
        )
        async with database.sessions() as session:
            with pytest.raises(ManagedResourceConflict, match="not usable"):
                await materializer._active_secret(session, UUID(created.json()["id"]))


@pytest.mark.asyncio
async def test_scope_and_secret_envelope_are_storage_immutable(
    migrated_database_url: str,
) -> None:
    async with client_for(migrated_database_url) as (client, database):
        created = await create(client, "immutable", {"type": "platform"})
        credential_id = UUID(created.json()["id"])
        tenant = await create(
            client,
            "immutable-tenant",
            {"type": "tenant", "tenant_id": "tenant-1"},
        )
        with pytest.raises(DBAPIError):
            async with database.sessions.begin() as session:
                await session.execute(
                    text(
                        "UPDATE control_plane.credentials SET scope_type='tenant', tenant_id='other' WHERE id=:id"
                    ),
                    {"id": credential_id},
                )
        with pytest.raises(DBAPIError):
            async with database.sessions.begin() as session:
                await session.execute(
                    text(
                        "UPDATE control_plane.credentials SET tenant_id='tenant-2' WHERE id=:id"
                    ),
                    {"id": UUID(tenant.json()["id"])},
                )
        with pytest.raises(DBAPIError):
            async with database.sessions.begin() as session:
                await session.execute(
                    text(
                        "UPDATE control_plane.credential_versions SET ciphertext='changed'::bytea WHERE credential_id=:id"
                    ),
                    {"id": credential_id},
                )


@pytest.mark.asyncio
async def test_credential_routes_enforce_permissions_and_command_headers(
    migrated_database_url: str,
) -> None:
    async with client_for(migrated_database_url, scopes="resources:read") as (
        reader,
        _,
    ):
        forbidden = await create(reader, "forbidden", {"type": "platform"})
        assert forbidden.status_code == 403
        assert forbidden.json()["code"] == "permission_denied"

    async with client_for(migrated_database_url) as (client, _):
        missing_key = await client.post(
            "/management/v1/credentials",
            json={
                "scope": {"type": "platform"},
                "name": "missing-key",
                "secret": "secret",
            },
        )
        assert missing_key.status_code == 400
        created = await create(client, "headers", {"type": "platform"})
        missing_match = await client.post(
            f"/management/v1/credentials/{created.json()['id']}/rotate",
            headers={"Idempotency-Key": "rotate"},
            json={"secret": "rotated"},
        )
        assert missing_match.status_code == 400
        assert "request_id" in missing_key.json()
        assert "request_id" in missing_match.json()
