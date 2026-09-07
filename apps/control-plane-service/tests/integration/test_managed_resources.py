import asyncio
import base64
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from control_plane.application.credentials import CredentialService
from control_plane.application.managed_resources import ManagedResourceService
from control_plane.domain.managed_resource_errors import (
    InvalidManagedResource,
    ManagedResourceConflict,
)
from control_plane.domain.managed_resources import (
    DeploymentKind,
    ModelDeployment,
    PlatformCredentialScope,
    ProviderConnection,
    STTCapabilities,
)
from control_plane.domain.providers import default_provider_registry
from control_plane.infrastructure.encryption import CredentialCipher
from control_plane.infrastructure.persistence.credential_transactions import (
    credential_command_scope,
)
from control_plane.infrastructure.persistence.database import Database
from control_plane.infrastructure.persistence.managed_resources import (
    SqlAlchemyManagedResourceRepository,
)
from control_plane.infrastructure.persistence.models import CredentialVersion
from control_plane.infrastructure.persistence.models import (
    ModelDeployment as ModelDeploymentRow,
)
from control_plane.infrastructure.persistence.models import (
    ProviderConnection as ProviderConnectionRow,
)
from control_plane.interfaces.http import create_http_app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

KEY = base64.b64encode(b"0" * 32).decode()


def resources(
    database: Database,
) -> tuple[
    CredentialService, ManagedResourceService, SqlAlchemyManagedResourceRepository
]:
    repository = SqlAlchemyManagedResourceRepository(database.sessions)
    credentials = CredentialService(
        credential_command_scope(database.sessions, CredentialCipher(KEY))
    )
    return (
        credentials,
        ManagedResourceService(default_provider_registry(), repository),
        repository,
    )


@pytest.mark.asyncio
async def test_credentials_are_encrypted_rotated_and_terminal(
    migrated_database_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    database = Database(migrated_database_url)
    credentials, _, repository = resources(database)
    secret = "plaintext-secret-never-persist-or-publish"
    try:
        created = await credentials.create(
            PlatformCredentialScope(), "azure-prod", secret, "alice", "create"
        )
        assert created.active_secret_version_number == 1
        assert created.generation == 1

        async with database.sessions() as session:
            stored = await session.scalar(select(CredentialVersion))
            assert stored is not None
            assert secret.encode() not in stored.ciphertext
            assert stored.key_id == "bootstrap"
            assert stored.algorithm == CredentialCipher.ALGORITHM

        second = await credentials.rotate(
            created.ref,
            "second-secret",
            credentials.concurrency_token(created),
            "bob",
            "rotate-2",
        )
        third = await credentials.rotate(
            created.ref,
            "third-secret",
            credentials.concurrency_token(second),
            "carol",
            "rotate-3",
        )
        assert third.ref == created.ref
        versions = await repository.list_credential_versions(created.ref)
        assert [value.version_number for value in versions] == [1, 2, 3]
        assert sum(value.retired_at is None for value in versions) == 1
        assert (await credentials.get(created.ref)).generation == 3

        revoked = await credentials.revoke(
            created.ref,
            credentials.concurrency_token(third),
            "dave",
            "revoke",
        )
        assert revoked.status == "revoked" and revoked.active_version_id is not None
        assert revoked.generation == 4
        assert [
            value.version_number
            for value in await repository.list_credential_versions(created.ref)
        ] == [1, 2, 3]
        with pytest.raises(ManagedResourceConflict, match="cannot be rotated"):
            await credentials.rotate(
                created.ref,
                "fourth",
                credentials.concurrency_token(revoked),
                "dave",
                "rotate-4",
            )
        assert secret not in caplog.text
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_resource_validation_optimistic_concurrency_and_no_cascade(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    credentials, service, _ = resources(database)
    try:
        credential = await credentials.create(
            PlatformCredentialScope(), "eleven-prod", "secret", "alice", "create"
        )
        connection = await service.create_connection(
            "elevenlabs-prod", "elevenlabs", credential.ref, {}, True, "alice"
        )
        deployment = await service.create_deployment(
            "scribe-prod",
            connection.ref,
            DeploymentKind.STT,
            {"model_id": "scribe_v2_realtime"},
            True,
            "alice",
            stt_capabilities=STTCapabilities(True, False),
        )

        deployment_updates = await asyncio.gather(
            service.update_deployment(
                deployment.ref,
                connection.ref,
                {"model_id": "scribe_v2_realtime"},
                1,
                "bob",
                stt_capabilities=STTCapabilities(True, False),
            ),
            service.update_deployment(
                deployment.ref,
                connection.ref,
                {"model_id": "scribe_v2_realtime"},
                1,
                "carol",
                stt_capabilities=STTCapabilities(True, False),
            ),
            return_exceptions=True,
        )
        assert (
            sum(isinstance(value, ModelDeployment) for value in deployment_updates) == 1
        )
        assert (
            sum(
                isinstance(value, ManagedResourceConflict)
                for value in deployment_updates
            )
            == 1
        )
        assert (await service.get_deployment(deployment.ref)).generation == 2

        results = await asyncio.gather(
            service.set_connection_enabled(connection.ref, False, 1, "bob"),
            service.set_connection_enabled(connection.ref, False, 1, "carol"),
            return_exceptions=True,
        )
        assert sum(isinstance(value, ProviderConnection) for value in results) == 1
        assert sum(isinstance(value, ManagedResourceConflict) for value in results) == 1
        assert (await service.get_connection(connection.ref)).generation == 2
        assert (await service.get_deployment(deployment.ref)).enabled is True

        connection = await service.get_connection(connection.ref)
        with pytest.raises(InvalidManagedResource, match="enabled connection"):
            await service.set_deployment_enabled(deployment.ref, False, 2, "bob")
            await service.set_deployment_enabled(deployment.ref, True, 3, "bob")

        await credentials.revoke(
            credential.ref,
            credentials.concurrency_token(credential),
            "security",
            "revoke",
        )
        assert (await service.get_connection(connection.ref)).enabled is False
        assert (await service.get_deployment(deployment.ref)).enabled is False
        with pytest.raises(InvalidManagedResource, match="active credential"):
            await service.set_connection_enabled(connection.ref, True, 2, "bob")
        with pytest.raises(InvalidManagedResource, match="active credential"):
            await service.create_connection(
                "revoked-active", "elevenlabs", credential.ref, {}, True, "bob"
            )

        async with database.sessions() as session:
            connection_rows = await session.scalar(
                select(func.count()).select_from(ProviderConnectionRow)
            )
            deployment_rows = await session.scalar(
                select(func.count()).select_from(ModelDeploymentRow)
            )
            assert connection_rows == deployment_rows == 1
        with pytest.raises(IntegrityError):
            async with database.sessions.begin() as session:
                await session.execute(
                    text(
                        "INSERT INTO control_plane.provider_connections "
                        "(id, key, provider_kind, credential_id, connection_config, enabled, generation, created_by, updated_by) "
                        "VALUES (:id, 'bad-fk', 'elevenlabs', :credential_id, '{}'::jsonb, false, 1, 'test', 'test')"
                    ),
                    {"id": uuid4(), "credential_id": uuid4()},
                )
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_http_lifecycle_and_secret_free_responses(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    credentials, service, _ = resources(database)

    class Lifecycle:
        @asynccontextmanager
        async def lifespan(self, _app: Any):
            yield

    app = create_http_app(
        Lifecycle(),
        managed_resources=service,  # type: ignore[arg-type]
        credentials=credentials,
    )
    app.state.settings = SimpleNamespace(
        control_plane_management_token=SimpleNamespace(
            get_secret_value=lambda: "management-secret"
        ),
        control_plane_management_actor="admin",
        control_plane_management_scopes="resources:read,credentials:write",
    )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            client.headers["Authorization"] = "Bearer management-secret"
            response = await client.post(
                "/management/v1/credentials",
                headers={"Idempotency-Key": "create-http"},
                json={
                    "scope": {"type": "platform"},
                    "name": "http-azure",
                    "secret": "http-secret",
                },
            )
            assert response.status_code == 201
            assert "http-secret" not in response.text
            credential_id = response.json()["id"]
            credential_etag = response.headers["etag"]
            duplicate = await client.post(
                "/management/v1/credentials",
                headers={"Idempotency-Key": "create-http"},
                json={
                    "scope": {"type": "platform"},
                    "name": "http-azure",
                    "secret": "other",
                },
            )
            assert duplicate.status_code == 409
            assert "other" not in duplicate.text

            response = await client.post(
                "/v1/managed-resources/provider-connections",
                json={
                    "key": "azure-http",
                    "provider_kind": "azure_openai",
                    "credential_ref": credential_id,
                    "connection_config": {
                        "endpoint": "https://example.openai.azure.com"
                    },
                    "enabled": True,
                    "actor": "admin",
                },
            )
            assert response.status_code == 201
            connection_id = response.json()["id"]

            response = await client.post(
                "/v1/managed-resources/model-deployments",
                json={
                    "key": "azure-chat-http",
                    "connection_ref": connection_id,
                    "deployment_kind": "llm",
                    "deployment_config": {
                        "deployment_name": "chat",
                        "model": "gpt-5.6-terra",
                        "api_version": "2025-01-01-preview",
                    },
                    "llm_capabilities": {
                        "supports_temperature": False,
                        "supports_reasoning_effort": True,
                    },
                    "enabled": True,
                    "actor": "admin",
                },
            )
            assert response.status_code == 201
            deployment_id = response.json()["id"]

            response = await client.post(
                f"/v1/managed-resources/model-deployments/{deployment_id}/disable",
                json={"expected_generation": 1, "actor": "admin"},
            )
            assert response.status_code == 200 and response.json()["generation"] == 2
            response = await client.post(
                f"/v1/managed-resources/model-deployments/{deployment_id}/enable",
                json={"expected_generation": 2, "actor": "admin"},
            )
            assert response.status_code == 200 and response.json()["generation"] == 3
            response = await client.post(
                f"/v1/managed-resources/provider-connections/{connection_id}/disable",
                json={"expected_generation": 1, "actor": "admin"},
            )
            assert response.status_code == 200 and response.json()["generation"] == 2
            response = await client.post(
                f"/v1/managed-resources/provider-connections/{connection_id}/enable",
                json={"expected_generation": 2, "actor": "admin"},
            )
            assert response.status_code == 200 and response.json()["generation"] == 3

            assert (
                await client.put(
                    f"/v1/managed-resources/provider-connections/{connection_id}",
                    json={
                        "credential_ref": credential_id,
                        "connection_config": {"bad": True},
                        "expected_generation": 1,
                        "actor": "admin",
                    },
                )
            ).status_code == 422
            assert (
                await client.post(
                    f"/v1/managed-resources/provider-connections/{connection_id}/disable",
                    json={"expected_generation": 99, "actor": "admin"},
                )
            ).status_code == 409
            assert (
                await client.get(
                    "/management/v1/credentials/00000000-0000-0000-0000-000000000000"
                )
            ).status_code == 404
            response = await client.post(
                f"/management/v1/credentials/{credential_id}/rotate",
                headers={"Idempotency-Key": "rotate-http", "If-Match": credential_etag},
                json={"secret": "rotated-http-secret"},
            )
            assert response.status_code == 200
            assert response.json()["active_secret_version"] == 2
            response = await client.post(
                f"/management/v1/credentials/{credential_id}/revoke",
                headers={
                    "Idempotency-Key": "revoke-http",
                    "If-Match": response.headers["etag"],
                },
            )
            assert (
                response.status_code == 200 and response.json()["status"] == "revoked"
            )
            response = await client.post(
                f"/management/v1/credentials/{credential_id}/rotate",
                headers={
                    "Idempotency-Key": "rejected-http",
                    "If-Match": response.headers["etag"],
                },
                json={"secret": "rejected-secret"},
            )
            assert (
                response.status_code == 409 and "rejected-secret" not in response.text
            )
            assert (
                "http-secret"
                not in (await client.get("/management/v1/credentials")).text
            )
    finally:
        await database.close()
