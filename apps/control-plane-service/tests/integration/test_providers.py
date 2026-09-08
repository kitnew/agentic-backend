import base64
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from control_plane.application.command_support import IdempotencyKeyReused
from control_plane.application.credentials import CredentialService
from control_plane.application.providers import (
    ProviderService,
    ProviderValidationResult,
)
from control_plane.domain.managed_resource_errors import (
    InvalidManagedResource,
    ManagedResourceConflict,
    ManagedResourcePreconditionFailed,
)
from control_plane.domain.managed_resources import (
    CredentialStatus,
    DeploymentKind,
    LLMCapabilities,
    PlatformCredentialScope,
    RealtimeCapabilities,
    STTCapabilities,
    TenantCredentialScope,
    TTSCapabilities,
)
from control_plane.domain.registries import DeploymentKindRegistry, ProviderKindRegistry
from control_plane.infrastructure.encryption import CredentialCipher
from control_plane.infrastructure.persistence.credential_transactions import (
    credential_command_scope,
)
from control_plane.infrastructure.persistence.database import Database
from control_plane.infrastructure.persistence.idempotency import (
    SqlAlchemyIdempotencyRepository,
)
from control_plane.infrastructure.persistence.models import IdempotencyReplay
from control_plane.infrastructure.persistence.models import (
    ProviderConnection as ProviderConnectionRow,
)
from control_plane.infrastructure.persistence.provider_transactions import (
    provider_command_scope,
)
from control_plane.infrastructure.persistence.providers import (
    SqlAlchemyProviderRepository,
)
from control_plane.interfaces.http import create_http_app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

KEY = base64.b64encode(b"0" * 32).decode()


class Validator:
    async def validate_connection(self, _kind, _config, secret):
        assert secret == "provider-secret"
        return ProviderValidationResult(True, True)

    async def validate_deployment(self, _kind, _connection, _deployment, _config, secret):
        assert secret == "provider-secret"
        return ProviderValidationResult(True, True)


def services(database: Database) -> tuple[CredentialService, ProviderService]:
    cipher = CredentialCipher(KEY)
    return (
        CredentialService(credential_command_scope(database.sessions, cipher)),
        ProviderService(
            provider_command_scope(database.sessions, cipher),
            ProviderKindRegistry(),
            DeploymentKindRegistry(),
            Validator(),
        ),
    )


@pytest.mark.asyncio
async def test_credential_revoke_rejects_enabled_provider_dependents_atomically(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    credentials, providers = services(database)
    try:
        credential = await credentials.create(
            PlatformCredentialScope(),
            "dependency",
            "provider-secret",
            "alice",
            "credential",
        )
        connection = await providers.create_connection(
            "dependency", "elevenlabs", credential.ref, {}, "alice", "connection"
        )
        connection = await providers.enable_connection(
            connection.ref,
            providers.concurrency_token(connection),
            "alice",
            "enable-connection",
        )

        with pytest.raises(ManagedResourceConflict, match="enabled provider connection"):
            await credentials.revoke(
                credential.ref,
                credentials.concurrency_token(credential),
                "alice",
                "blocked-revoke",
            )

        assert (await credentials.get(credential.ref)).status is CredentialStatus.ACTIVE
        assert (await providers.get_connection(connection.ref)).enabled
        async with database.sessions() as session:
            assert await session.scalar(
                select(func.count())
                .select_from(IdempotencyReplay)
                .where(IdempotencyReplay.idempotency_key == "blocked-revoke")
            ) == 0

        connection = await providers.disable_connection(
            connection.ref,
            providers.concurrency_token(connection),
            "alice",
            "disable-connection",
        )
        revoked = await credentials.revoke(
            credential.ref,
            credentials.concurrency_token(credential),
            "alice",
            "blocked-revoke",
        )
        assert revoked.status is CredentialStatus.REVOKED
        assert (await providers.get_connection(connection.ref)).credential_ref == credential.ref
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_provider_disable_rejects_enabled_deployment_dependents_atomically(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    credentials, providers = services(database)
    try:
        credential = await credentials.create(
            PlatformCredentialScope(),
            "dependency",
            "provider-secret",
            "alice",
            "credential",
        )
        connection = await providers.create_connection(
            "dependency", "elevenlabs", credential.ref, {}, "alice", "connection"
        )
        connection = await providers.enable_connection(
            connection.ref,
            providers.concurrency_token(connection),
            "alice",
            "enable-connection",
        )
        deployment = await providers.create_deployment(
            "dependency",
            connection.ref,
            DeploymentKind.TTS,
            {"model_id": "flash"},
            TTSCapabilities(),
            "alice",
            "deployment",
        )
        deployment = await providers.enable_deployment(
            deployment.ref,
            providers.concurrency_token(deployment),
            "alice",
            "enable-deployment",
        )

        with pytest.raises(ManagedResourceConflict, match="enabled model deployment"):
            await providers.disable_connection(
                connection.ref,
                providers.concurrency_token(connection),
                "alice",
                "blocked-disable",
            )

        assert (await providers.get_connection(connection.ref)).enabled
        assert (await providers.get_deployment(deployment.ref)).enabled
        async with database.sessions() as session:
            assert await session.scalar(
                select(func.count())
                .select_from(IdempotencyReplay)
                .where(IdempotencyReplay.idempotency_key == "blocked-disable")
            ) == 0

        deployment = await providers.disable_deployment(
            deployment.ref,
            providers.concurrency_token(deployment),
            "alice",
            "disable-deployment",
        )
        connection = await providers.disable_connection(
            connection.ref,
            providers.concurrency_token(connection),
            "alice",
            "blocked-disable",
        )
        assert not deployment.enabled and not connection.enabled
        assert (await providers.get_deployment(deployment.ref)).connection_ref == connection.ref
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_provider_persistence_ownership_identity_and_capabilities(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    credentials, providers = services(database)
    try:
        platform = await credentials.create(
            PlatformCredentialScope(),
            "platform",
            "provider-secret",
            "alice",
            "platform",
        )
        tenant = await credentials.create(
            TenantCredentialScope("tenant-a"),
            "tenant",
            "tenant-secret",
            "alice",
            "tenant",
        )
        with pytest.raises(InvalidManagedResource, match="platform credential"):
            await providers.create_connection(
                "tenant-credential", "elevenlabs", tenant.ref, {}, "alice", "bad"
            )
        with pytest.raises(InvalidManagedResource, match="does not exist"):
            await providers.create_connection(
                "missing", "elevenlabs", type(platform.ref)(uuid4()), {}, "alice", "missing"
            )

        connection = await providers.create_connection(
            "azure",
            "azure_openai",
            platform.ref,
            {"endpoint": "https://example.openai.azure.com"},
            "alice",
            "connection",
        )
        with pytest.raises(ManagedResourceConflict):
            await providers.create_connection(
                "azure",
                "azure_openai",
                platform.ref,
                {"endpoint": "https://example.openai.azure.com"},
                "alice",
                "duplicate-connection",
            )
        assert not connection.enabled
        enabled_connection = await providers.enable_connection(
            connection.ref,
            providers.concurrency_token(connection),
            "alice",
            "enable-connection",
        )

        values = (
            (DeploymentKind.LLM, LLMCapabilities(True, True), {"deployment_name": "chat", "model": "gpt", "api_version": "v1"}),
            (DeploymentKind.REALTIME, RealtimeCapabilities(True, True), {"deployment_name": "realtime"}),
            (DeploymentKind.STT, STTCapabilities(True, True), {"deployment_name": "stt"}),
        )
        deployments = []
        for index, (kind, capabilities, config) in enumerate(values):
            deployment = await providers.create_deployment(
                f"deployment-{index}", enabled_connection.ref, kind, config,
                capabilities, "alice", f"create-{index}"
            )
            assert deployment.capabilities.kind == kind.value and not deployment.enabled
            deployments.append(deployment)

        eleven = await providers.create_connection(
            "eleven", "elevenlabs", platform.ref, {}, "alice", "eleven"
        )
        tts = await providers.create_deployment(
            "tts", eleven.ref, DeploymentKind.TTS, {"model_id": "flash"},
            TTSCapabilities(), "alice", "tts"
        )
        with pytest.raises(InvalidManagedResource, match="provider connection is disabled"):
            await providers.enable_deployment(
                tts.ref, providers.concurrency_token(tts), "alice", "enable-tts"
            )

        async with database.sessions.begin() as session:
            with pytest.raises(DBAPIError, match="identity is immutable"):
                await session.execute(
                    text("UPDATE control_plane.provider_connections SET key='changed' WHERE id=:id"),
                    {"id": connection.ref.value},
                )
        async with database.sessions.begin() as session:
            with pytest.raises(DBAPIError, match="identity is immutable"):
                await session.execute(
                    text("UPDATE control_plane.provider_connections SET provider_kind='deepgram' WHERE id=:id"),
                    {"id": connection.ref.value},
                )
        async with database.sessions.begin() as session:
            with pytest.raises(DBAPIError, match="identity is immutable"):
                await session.execute(
                    text("UPDATE control_plane.model_deployments SET key='changed' WHERE id=:id"),
                    {"id": deployments[0].ref.value},
                )
        async with database.sessions.begin() as session:
            with pytest.raises(DBAPIError, match="identity is immutable"):
                await session.execute(
                    text("UPDATE control_plane.model_deployments SET deployment_kind='tts' WHERE id=:id"),
                    {"id": deployments[0].ref.value},
                )
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_provider_idempotency_concurrency_atomicity_and_validation_boundary(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    credentials, providers = services(database)
    try:
        credential = await credentials.create(
            PlatformCredentialScope(), "platform", "provider-secret", "alice", "credential"
        )
        connection = await providers.create_connection(
            "eleven", "elevenlabs", credential.ref, {}, "alice", "create"
        )
        replay = await providers.create_connection(
            "eleven", "elevenlabs", credential.ref, {}, "alice", "create"
        )
        assert replay == connection
        with pytest.raises(IdempotencyKeyReused):
            await providers.create_connection(
                "changed", "elevenlabs", credential.ref, {}, "alice", "create"
            )
        enabled = await providers.enable_connection(
            connection.ref, providers.concurrency_token(connection), "alice", "enable"
        )
        with pytest.raises(ManagedResourcePreconditionFailed):
            await providers.disable_connection(enabled.ref, "stale", "alice", "stale")
        disabled = await providers.disable_connection(
            enabled.ref, providers.concurrency_token(enabled), "alice", "disable"
        )
        assert await providers.disable_connection(
            enabled.ref, providers.concurrency_token(enabled), "alice", "disable"
        ) == disabled
        await providers.enable_connection(
            disabled.ref, providers.concurrency_token(disabled), "alice", "enable-again"
        )
        before = await providers.get_connection(connection.ref)
        assert (await providers.validate_connection(connection.ref)).usable
        assert await providers.get_connection(connection.ref) == before

        async with database.sessions() as session:
            assert await session.scalar(select(func.count()).select_from(ProviderConnectionRow)) == 1
            assert await session.scalar(select(func.count()).select_from(IdempotencyReplay)) >= 4

        cipher = CredentialCipher(KEY)

        @asynccontextmanager
        async def failing_scope():
            async with database.sessions.begin() as session:
                repository = SqlAlchemyProviderRepository(session, cipher)
                replay_repository = SqlAlchemyIdempotencyRepository(session)

                async def fail(*_args, **_kwargs):
                    raise RuntimeError("replay write failed")

                replay_repository.add = fail  # type: ignore[method-assign]
                yield repository, replay_repository

        failing = ProviderService(
            failing_scope,
            ProviderKindRegistry(),
            DeploymentKindRegistry(),
            Validator(),
        )
        with pytest.raises(RuntimeError, match="replay write failed"):
            await failing.create_connection(
                "rolled-back", "elevenlabs", credential.ref, {}, "alice", "rollback"
            )
        assert all(
            value.key != "rolled-back" for value in await providers.list_connections()
        )
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_provider_http_contract_is_secret_free_and_retry_safe(
    migrated_database_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    database = Database(migrated_database_url)
    credentials, providers = services(database)

    class Lifecycle:
        @asynccontextmanager
        async def lifespan(self, _app: Any):
            yield

    app = create_http_app(
        Lifecycle(), credentials=credentials, providers=providers  # type: ignore[arg-type]
    )
    app.state.settings = SimpleNamespace(
        control_plane_management_token=SimpleNamespace(
            get_secret_value=lambda: "management-secret"
        ),
        control_plane_management_actor="admin",
        control_plane_management_scopes="resources:read,resources:write,credentials:write",
    )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (
                await client.get("/management/v1/providers/connections")
            ).status_code == 401
            client.headers["Authorization"] = "Bearer management-secret"
            credential_response = await client.post(
                "/management/v1/credentials",
                headers={"Idempotency-Key": "credential"},
                json={
                    "scope": {"type": "platform"},
                    "name": "provider",
                    "secret": "provider-secret",
                },
            )
            credential_id = credential_response.json()["id"]
            connection_body = {
                "key": "eleven",
                "provider_kind": "elevenlabs",
                "credential_ref": credential_id,
                "connection_config": {},
            }
            assert (
                await client.post(
                    "/management/v1/providers/connections", json=connection_body
                )
            ).status_code == 400
            response = await client.post(
                "/management/v1/providers/connections",
                headers={"Idempotency-Key": "connection"},
                json=connection_body,
            )
            assert response.status_code == 201
            assert "provider-secret" not in response.text
            assert "generation" not in response.json() and "created_by" not in response.json()
            connection_id = response.json()["id"]
            first_etag = response.headers["etag"]

            assert (
                await client.post(
                    f"/management/v1/providers/connections/{connection_id}/enable",
                    headers={"Idempotency-Key": "missing-precondition"},
                )
                ).status_code == 400
            enabled = await client.post(
                f"/management/v1/providers/connections/{connection_id}/enable",
                headers={"Idempotency-Key": "enable", "If-Match": first_etag},
            )
            assert enabled.status_code == 200 and enabled.json()["enabled"]
            replay = await client.post(
                f"/management/v1/providers/connections/{connection_id}/enable",
                headers={"Idempotency-Key": "enable", "If-Match": first_etag},
            )
            assert replay.status_code == 200 and replay.json() == enabled.json()
            stale = await client.post(
                f"/management/v1/providers/connections/{connection_id}/disable",
                headers={"Idempotency-Key": "stale", "If-Match": first_etag},
            )
            assert stale.status_code == 412
            validation = await client.post(
                f"/management/v1/providers/connections/{connection_id}/validate"
            )
            assert validation.status_code == 200 and validation.json()["usable"]
            assert "provider-secret" not in validation.text

            deployment_body = {
                "key": "tts",
                "connection_ref": connection_id,
                "deployment_kind": "tts",
                "deployment_config": {"model_id": "flash"},
                "capabilities": {"kind": "tts"},
            }
            mismatch = await client.post(
                "/management/v1/providers/deployments",
                headers={"Idempotency-Key": "mismatch"},
                json={
                    **deployment_body,
                    "capabilities": {
                        "kind": "stt",
                        "supports_cascade": True,
                        "supports_realtime_input_transcription": False,
                    },
                },
            )
            assert mismatch.status_code == 422
            deployment = await client.post(
                "/management/v1/providers/deployments",
                headers={"Idempotency-Key": "deployment"},
                json=deployment_body,
            )
            assert deployment.status_code == 201
            assert deployment.json()["capabilities"] == {"kind": "tts"}
            assert "generation" not in deployment.json()
            deployment_id = deployment.json()["id"]
            deployment_etag = deployment.headers["etag"]
            enabled_deployment = await client.post(
                f"/management/v1/providers/deployments/{deployment_id}/enable",
                headers={
                    "Idempotency-Key": "enable-deployment",
                    "If-Match": deployment_etag,
                },
            )
            assert enabled_deployment.status_code == 200
            deployment_validation = await client.post(
                f"/management/v1/providers/deployments/{deployment_id}/validate"
            )
            assert deployment_validation.status_code == 200
            assert deployment_validation.json()["usable"]
            updated_deployment = await client.put(
                f"/management/v1/providers/deployments/{deployment_id}",
                headers={
                    "Idempotency-Key": "update-deployment",
                    "If-Match": enabled_deployment.headers["etag"],
                },
                json={
                    "connection_ref": connection_id,
                    "deployment_config": {"model_id": "turbo"},
                    "capabilities": {"kind": "tts"},
                },
            )
            assert updated_deployment.status_code == 200
            disabled_deployment = await client.post(
                f"/management/v1/providers/deployments/{deployment_id}/disable",
                headers={
                    "Idempotency-Key": "disable-deployment",
                    "If-Match": updated_deployment.headers["etag"],
                },
            )
            assert disabled_deployment.status_code == 200
            assert len(
                (await client.get("/management/v1/providers/deployments")).json()
            ) == 1
            assert (
                await client.get(
                    f"/management/v1/providers/deployments/{deployment_id}"
                )
            ).status_code == 200
            assert (
                await client.get("/v1/managed-resources/provider-connections")
            ).status_code == 404
            assert "provider-secret" not in caplog.text
    finally:
        await database.close()
