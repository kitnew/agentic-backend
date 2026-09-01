import asyncio
import base64
import json
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import pytest
from contracts import ManagedResourceChangedV1
from control_plane.application.managed_resources import ManagedResourceService
from control_plane.application.ports.messaging import OutboundMessage
from control_plane.domain.managed_resource_errors import (
    InvalidManagedResource,
    ManagedResourceConflict,
)
from control_plane.domain.managed_resources import (
    DeploymentKind,
    ModelDeployment,
    ProviderConnection,
    STTCapabilities,
)
from control_plane.domain.providers import default_provider_registry
from control_plane.infrastructure.encryption import CredentialCipher
from control_plane.infrastructure.messaging.outbox import OutboxRelay
from control_plane.infrastructure.persistence.database import Database
from control_plane.infrastructure.persistence.managed_resources import (
    SqlAlchemyManagedResourceRepository,
)
from control_plane.infrastructure.persistence.models import (
    CredentialVersion,
    OutboxMessage,
)
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
) -> tuple[ManagedResourceService, SqlAlchemyManagedResourceRepository]:
    repository = SqlAlchemyManagedResourceRepository(
        database.sessions, CredentialCipher(KEY)
    )
    return ManagedResourceService(default_provider_registry(), repository), repository


class RecordingPublisher:
    def __init__(self) -> None:
        self.messages: list[OutboundMessage] = []

    async def publish(self, message: OutboundMessage) -> None:
        self.messages.append(message)
        if len(self.messages) == 1:
            raise RuntimeError("temporary failure")


class BlockingPublisher:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.messages: list[OutboundMessage] = []

    async def publish(self, message: OutboundMessage) -> None:
        self.messages.append(message)
        self.started.set()
        await self.release.wait()


class CollectingPublisher:
    def __init__(self) -> None:
        self.messages: list[OutboundMessage] = []

    async def publish(self, message: OutboundMessage) -> None:
        self.messages.append(message)


@pytest.mark.asyncio
async def test_credentials_are_encrypted_rotated_and_terminal(
    migrated_database_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    database = Database(migrated_database_url)
    service, repository = resources(database)
    secret = "plaintext-secret-never-persist-or-publish"
    try:
        created = await service.create_credential("azure-prod", secret, "alice")
        assert created.active_secret_version_number == 1
        assert created.generation == 1
        assert await repository.resolve_secret(created.ref) == secret

        async with database.sessions() as session:
            stored = await session.scalar(select(CredentialVersion))
            event = await session.scalar(select(OutboxMessage))
            assert stored is not None and event is not None
            assert secret.encode() not in stored.ciphertext
            assert stored.key_id == "bootstrap"
            assert stored.algorithm == CredentialCipher.ALGORITHM
            assert secret not in json.dumps(event.payload)

        publisher = RecordingPublisher()
        relay = OutboxRelay(database.sessions, publisher)
        assert await relay.relay_once()
        assert await relay.relay_once()
        assert publisher.messages[0].message_id == publisher.messages[1].message_id
        published = ManagedResourceChangedV1.model_validate_json(
            publisher.messages[1].payload
        )
        assert published.payload.action == "created"
        assert secret not in publisher.messages[1].payload.decode()

        rotations = await asyncio.gather(
            service.rotate_credential(created.ref, "second-secret", "bob"),
            service.rotate_credential(created.ref, "third-secret", "carol"),
        )
        assert {value.ref for value in rotations} == {created.ref}
        versions = await repository.list_credential_versions(created.ref)
        assert [value.version_number for value in versions] == [1, 2, 3]
        assert sum(value.retired_at is None for value in versions) == 1
        assert (await service.get_credential(created.ref)).generation == 3

        revoked = await service.revoke_credential(created.ref, "dave")
        assert revoked.status == "revoked" and revoked.active_version_id is None
        assert revoked.generation == 4
        assert [value.version_number for value in await repository.list_credential_versions(created.ref)] == [1, 2, 3]
        async with database.sessions() as session:
            events = (
                await session.scalars(
                    select(OutboxMessage)
                    .where(OutboxMessage.ordering_key == f"managed:credential:{created.ref.value}")
                    .order_by(OutboxMessage.ordering_sequence)
                )
            ).all()
        assert [
            (
                ManagedResourceChangedV1.model_validate(event.payload).payload.action,
                ManagedResourceChangedV1.model_validate(event.payload).payload.resource_generation,
            )
            for event in events
        ] == [("created", 1), ("rotated", 2), ("rotated", 3), ("revoked", 4)]
        with pytest.raises(ManagedResourceConflict, match="cannot be rotated"):
            await service.rotate_credential(created.ref, "fourth", "dave")
        with pytest.raises(ManagedResourceConflict, match="not usable"):
            await repository.resolve_secret(created.ref)
        assert secret not in caplog.text
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_resource_validation_optimistic_concurrency_and_no_cascade(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    service, _ = resources(database)
    try:
        credential = await service.create_credential("eleven-prod", "secret", "alice")
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

        await service.revoke_credential(credential.ref, "security")
        assert (await service.get_connection(connection.ref)).enabled is False
        assert (await service.get_deployment(deployment.ref)).enabled is False
        async with database.sessions() as session:
            before = await session.scalar(
                select(func.count()).select_from(OutboxMessage)
            )
        with pytest.raises(InvalidManagedResource, match="active credential"):
            await service.set_connection_enabled(connection.ref, True, 2, "bob")
        with pytest.raises(InvalidManagedResource, match="active credential"):
            await service.create_connection(
                "revoked-active", "elevenlabs", credential.ref, {}, True, "bob"
            )

        async with database.sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(OutboxMessage))
                == before
            )
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
async def test_managed_outbox_preserves_resource_order_but_not_global_order(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    service, _ = resources(database)
    first_publisher = BlockingPublisher()
    second_publisher = CollectingPublisher()
    first = OutboxRelay(database.sessions, first_publisher)
    second = OutboxRelay(database.sessions, second_publisher)
    try:
        credential = await service.create_credential("ordered", "first", "alice")
        await service.rotate_credential(credential.ref, "second", "alice")

        in_flight = asyncio.create_task(first.relay_once())
        await first_publisher.started.wait()
        assert not await second.relay_once()
        first_publisher.release.set()
        assert await in_flight
        assert await second.relay_once()
        actions = [
            ManagedResourceChangedV1.model_validate_json(message.payload).payload.action
            for message in [*first_publisher.messages, *second_publisher.messages]
        ]
        assert actions == ["created", "rotated"]

        other = await service.create_credential("independent", "third", "bob")
        assert other.generation == 1
        await service.create_credential("also-independent", "fourth", "bob")
        first_publisher.started.clear()
        first_publisher.release.clear()
        in_flight = asyncio.create_task(first.relay_once())
        await first_publisher.started.wait()
        assert await second.relay_once()
        first_publisher.release.set()
        assert await in_flight
        assert second_publisher.messages[-1].message_id != first_publisher.messages[-1].message_id
    finally:
        first_publisher.release.set()
        await database.close()


@pytest.mark.asyncio
async def test_http_lifecycle_and_secret_free_responses(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    service, _ = resources(database)

    class Lifecycle:
        @asynccontextmanager
        async def lifespan(self, _app: Any):
            yield

    app = create_http_app(
        Lifecycle(),
        managed_resources=service,  # type: ignore[arg-type]
    )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/v1/managed-resources/credentials",
                json={"name": "http-azure", "secret": "http-secret", "actor": "admin"},
            )
            assert response.status_code == 201
            assert "http-secret" not in response.text
            credential_id = response.json()["id"]
            duplicate = await client.post(
                "/v1/managed-resources/credentials",
                json={"name": "http-azure", "secret": "other", "actor": "admin"},
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
                    "/v1/managed-resources/credentials/00000000-0000-0000-0000-000000000000"
                )
            ).status_code == 404
            response = await client.post(
                f"/v1/managed-resources/credentials/{credential_id}/rotate",
                json={"secret": "rotated-http-secret", "actor": "admin"},
            )
            assert response.status_code == 200
            assert response.json()["active_secret_version_number"] == 2
            response = await client.post(
                f"/v1/managed-resources/credentials/{credential_id}/revoke",
                json={"actor": "admin"},
            )
            assert (
                response.status_code == 200 and response.json()["status"] == "revoked"
            )
            response = await client.post(
                f"/v1/managed-resources/credentials/{credential_id}/rotate",
                json={"secret": "rejected-secret", "actor": "admin"},
            )
            assert (
                response.status_code == 409 and "rejected-secret" not in response.text
            )
            assert (
                "http-secret"
                not in (await client.get("/v1/managed-resources/credentials")).text
            )
    finally:
        await database.close()
