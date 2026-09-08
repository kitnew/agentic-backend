from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from control_plane.application.command_support import IdempotencyKeyReused, StoredReplay
from control_plane.application.providers import (
    ProviderService,
    ProviderValidationResult,
)
from control_plane.domain.managed_resource_errors import (
    InvalidManagedResource,
    ManagedResourceConflict,
    ManagedResourceNotFound,
    ManagedResourcePreconditionFailed,
)
from control_plane.domain.managed_resources import (
    Credential,
    CredentialRef,
    CredentialStatus,
    DeploymentKind,
    LLMCapabilities,
    ModelDeployment,
    ModelDeploymentRef,
    PlatformCredentialScope,
    ProviderConnection,
    ProviderConnectionRef,
    RealtimeCapabilities,
    STTCapabilities,
    TenantCredentialScope,
    TTSCapabilities,
)
from control_plane.domain.registries import DeploymentKindRegistry, ProviderKindRegistry
from control_plane.interfaces.http.app import ModelDeploymentCreate
from pydantic import ValidationError

NOW = datetime.now(UTC)


class Replays:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str, str], StoredReplay] = {}

    async def get(self, principal: str, operation: str, key: str):
        return self.values.get((principal, operation, key))

    async def add(
        self,
        principal: str,
        operation: str,
        key: str,
        fingerprint: str,
        result: dict[str, object],
    ) -> None:
        self.values[(principal, operation, key)] = StoredReplay(fingerprint, result)


class Repository:
    def __init__(self) -> None:
        self.credentials: dict[CredentialRef, Credential] = {}
        self.connections: dict[ProviderConnectionRef, ProviderConnection] = {}
        self.deployments: dict[ModelDeploymentRef, ModelDeployment] = {}
        self.connection_creates = 0

    async def get_credential(
        self, ref: CredentialRef, *, lock: bool = False
    ) -> Credential:
        try:
            return self.credentials[ref]
        except KeyError as error:
            raise ManagedResourceNotFound("credential not found") from error

    async def credential_secret(self, _credential: Credential) -> str:
        return "transient-secret"

    async def create_connection(self, key, kind, credential_ref, config, actor):
        self.connection_creates += 1
        value = ProviderConnection(
            ProviderConnectionRef(uuid4()),
            key,
            kind,
            credential_ref,
            config,
            False,
            1,
            NOW,
            actor,
            NOW,
            actor,
        )
        self.connections[value.ref] = value
        return value

    async def update_connection(self, connection, credential_ref, config, actor):
        value = replace(
            connection,
            credential_ref=credential_ref,
            connection_config=config,
            generation=connection.generation + 1,
            updated_by=actor,
        )
        self.connections[value.ref] = value
        return value

    async def set_connection_enabled(self, connection, enabled, actor):
        value = replace(
            connection,
            enabled=enabled,
            generation=connection.generation + 1,
            updated_by=actor,
        )
        self.connections[value.ref] = value
        return value

    async def get_connection(self, ref, *, lock=False):
        try:
            return self.connections[ref]
        except KeyError as error:
            raise ManagedResourceNotFound("connection not found") from error

    async def list_connections(self):
        return list(self.connections.values())

    async def create_deployment(
        self, key, connection_ref, kind, config, capabilities, actor
    ):
        value = ModelDeployment(
            ModelDeploymentRef(uuid4()),
            key,
            connection_ref,
            kind,
            config,
            capabilities,
            False,
            1,
            NOW,
            actor,
            NOW,
            actor,
        )
        self.deployments[value.ref] = value
        return value

    async def update_deployment(
        self, deployment, connection_ref, config, capabilities, actor
    ):
        value = replace(
            deployment,
            connection_ref=connection_ref,
            deployment_config=config,
            capabilities=capabilities,
            generation=deployment.generation + 1,
            updated_by=actor,
        )
        self.deployments[value.ref] = value
        return value

    async def set_deployment_enabled(self, deployment, enabled, actor):
        value = replace(
            deployment,
            enabled=enabled,
            generation=deployment.generation + 1,
            updated_by=actor,
        )
        self.deployments[value.ref] = value
        return value

    async def get_deployment(self, ref, *, lock=False):
        try:
            return self.deployments[ref]
        except KeyError as error:
            raise ManagedResourceNotFound("deployment not found") from error

    async def list_deployments(self):
        return list(self.deployments.values())

    async def has_enabled_deployments(self, ref: ProviderConnectionRef) -> bool:
        return any(
            value.connection_ref == ref and value.enabled
            for value in self.deployments.values()
        )

    async def is_referenced_by_system_configuration(self, _ref) -> bool:
        return False

    async def system_configuration_references(self, _ref):
        return ()


class Validator:
    def __init__(self, transaction: SimpleNamespace) -> None:
        self.transaction = transaction
        self.secrets: list[str] = []

    async def validate_connection(self, _kind, _config, secret):
        assert not self.transaction.active
        self.secrets.append(secret)
        return ProviderValidationResult(True, True)

    async def validate_deployment(self, _kind, _connection, _deployment, _config, secret):
        assert not self.transaction.active
        self.secrets.append(secret)
        return ProviderValidationResult(True, True)


def setup_service():
    repository = Repository()
    replays = Replays()
    transaction = SimpleNamespace(active=False)
    validator = Validator(transaction)

    @asynccontextmanager
    async def scope():
        transaction.active = True
        try:
            yield repository, replays
        finally:
            transaction.active = False

    service = ProviderService(
        scope, ProviderKindRegistry(), DeploymentKindRegistry(), validator
    )
    return service, repository, validator


def credential(scope=None, status=CredentialStatus.ACTIVE) -> Credential:
    return Credential(
        CredentialRef(uuid4()),
        scope or PlatformCredentialScope(),
        "provider",
        uuid4(),
        1,
        status,
        1,
        NOW,
        "test",
        NOW if status is CredentialStatus.REVOKED else None,
        "test" if status is CredentialStatus.REVOKED else None,
    )


@pytest.mark.asyncio
async def test_connection_scope_usability_idempotency_and_concurrency() -> None:
    service, repository, _ = setup_service()
    platform = credential()
    tenant = credential(TenantCredentialScope("tenant-a"))
    revoked = credential(status=CredentialStatus.REVOKED)
    repository.credentials = {value.ref: value for value in (platform, tenant, revoked)}

    connection = await service.create_connection(
        "eleven-prod", "elevenlabs", platform.ref, {}, "alice", "create"
    )
    replay = await service.create_connection(
        "eleven-prod", "elevenlabs", platform.ref, {}, "alice", "create"
    )
    assert replay == connection and repository.connection_creates == 1
    with pytest.raises(IdempotencyKeyReused):
        await service.create_connection(
            "changed", "elevenlabs", platform.ref, {}, "alice", "create"
        )
    with pytest.raises(InvalidManagedResource, match="platform credential"):
        await service.create_connection(
            "tenant", "elevenlabs", tenant.ref, {}, "alice", "tenant"
        )
    disabled_with_revoked = await service.create_connection(
        "revoked", "elevenlabs", revoked.ref, {}, "alice", "revoked"
    )
    with pytest.raises(InvalidManagedResource, match="revoked"):
        await service.enable_connection(
            disabled_with_revoked.ref,
            service.concurrency_token(disabled_with_revoked),
            "alice",
            "enable-revoked",
        )

    enabled = await service.enable_connection(
        connection.ref, service.concurrency_token(connection), "alice", "enable"
    )
    with pytest.raises(ManagedResourcePreconditionFailed):
        await service.disable_connection(connection.ref, "stale", "alice", "stale")
    disabled = await service.disable_connection(
        enabled.ref, service.concurrency_token(enabled), "alice", "disable"
    )
    assert disabled.ref == connection.ref and not disabled.enabled
    replay = await service.disable_connection(
        enabled.ref, service.concurrency_token(enabled), "alice", "disable"
    )
    assert replay == disabled


@pytest.mark.asyncio
async def test_deployment_unions_references_and_reference_preservation() -> None:
    service, repository, _ = setup_service()
    platform = credential()
    repository.credentials[platform.ref] = platform
    with pytest.raises(InvalidManagedResource, match="does not exist"):
        await service.create_deployment(
            "missing",
            ProviderConnectionRef(uuid4()),
            DeploymentKind.TTS,
            {"model_id": "flash"},
            TTSCapabilities(),
            "alice",
            "missing",
        )
    connection = await service.create_connection(
        "azure", "azure_openai", platform.ref,
        {"endpoint": "https://example.openai.azure.com"}, "alice", "connection"
    )
    enabled_connection = await service.enable_connection(
        connection.ref, service.concurrency_token(connection), "alice", "enable"
    )

    for index, (kind, capabilities, config) in enumerate(
        (
            (DeploymentKind.LLM, LLMCapabilities(True, True), {"deployment_name": "chat", "model": "gpt", "api_version": "v1"}),
            (DeploymentKind.REALTIME, RealtimeCapabilities(True, True), {"deployment_name": "realtime"}),
            (DeploymentKind.STT, STTCapabilities(True, True), {"deployment_name": "stt"}),
        )
    ):
        deployment = await service.create_deployment(
            f"deployment-{index}", enabled_connection.ref, kind, config,
            capabilities, "alice", f"create-{index}"
        )
        enabled = await service.enable_deployment(
            deployment.ref, service.concurrency_token(deployment), "alice", f"enable-{index}"
        )
        assert enabled.capabilities.kind == kind.value

    eleven = await service.create_connection(
        "eleven", "elevenlabs", platform.ref, {}, "alice", "eleven"
    )
    enabled_eleven = await service.enable_connection(
        eleven.ref, service.concurrency_token(eleven), "alice", "enable-eleven"
    )
    tts = await service.create_deployment(
        "tts", enabled_eleven.ref, DeploymentKind.TTS, {"model_id": "flash"},
        TTSCapabilities(), "alice", "tts"
    )
    with pytest.raises(InvalidManagedResource, match="capabilities"):
        await service.create_deployment(
            "bad", eleven.ref, DeploymentKind.TTS, {"model_id": "flash"},
            STTCapabilities(True, False), "alice", "bad"
        )
    enabled_tts = await service.enable_deployment(
        tts.ref, service.concurrency_token(tts), "alice", "enable-tts"
    )
    with pytest.raises(ManagedResourceConflict, match="enabled model deployment"):
        await service.disable_connection(
            enabled_eleven.ref,
            service.concurrency_token(enabled_eleven),
            "alice",
            "blocked-disable-connection",
        )
    disabled_tts = await service.disable_deployment(
        enabled_tts.ref,
        service.concurrency_token(enabled_tts),
        "alice",
        "disable-tts",
    )
    disabled_connection = await service.disable_connection(
        enabled_eleven.ref,
        service.concurrency_token(enabled_eleven),
        "alice",
        "disable-connection",
    )
    assert disabled_connection.ref == enabled_tts.connection_ref
    assert repository.deployments[tts.ref] == disabled_tts
    with pytest.raises(InvalidManagedResource, match="disabled"):
        await service.validate_deployment(tts.ref)


@pytest.mark.asyncio
async def test_all_provider_mutations_use_idempotency_and_concurrency() -> None:
    service, repository, _ = setup_service()
    platform = credential()
    repository.credentials[platform.ref] = platform
    connection = await service.create_connection(
        "eleven", "elevenlabs", platform.ref, {}, "alice", "connection"
    )
    enabled_connection = await service.enable_connection(
        connection.ref, service.concurrency_token(connection), "alice", "enable"
    )
    updated_connection = await service.update_connection(
        connection.ref,
        platform.ref,
        {},
        service.concurrency_token(enabled_connection),
        "alice",
        "update",
    )
    assert await service.update_connection(
        connection.ref,
        platform.ref,
        {},
        service.concurrency_token(enabled_connection),
        "alice",
        "update",
    ) == updated_connection
    with pytest.raises(IdempotencyKeyReused):
        await service.update_connection(
            connection.ref,
            platform.ref,
            {"changed": True},
            service.concurrency_token(enabled_connection),
            "alice",
            "update",
        )

    deployment = await service.create_deployment(
        "tts",
        updated_connection.ref,
        DeploymentKind.TTS,
        {"model_id": "flash"},
        TTSCapabilities(),
        "alice",
        "deployment",
    )
    assert await service.create_deployment(
        "tts",
        updated_connection.ref,
        DeploymentKind.TTS,
        {"model_id": "flash"},
        TTSCapabilities(),
        "alice",
        "deployment",
    ) == deployment
    with pytest.raises(IdempotencyKeyReused):
        await service.create_deployment(
            "tts-other",
            updated_connection.ref,
            DeploymentKind.TTS,
            {"model_id": "flash"},
            TTSCapabilities(),
            "alice",
            "deployment",
        )
    enabled = await service.enable_deployment(
        deployment.ref,
        service.concurrency_token(deployment),
        "alice",
        "enable-deployment",
    )
    assert await service.enable_deployment(
        deployment.ref,
        service.concurrency_token(deployment),
        "alice",
        "enable-deployment",
    ) == enabled
    updated = await service.update_deployment(
        deployment.ref,
        updated_connection.ref,
        {"model_id": "turbo"},
        TTSCapabilities(),
        service.concurrency_token(enabled),
        "alice",
        "update-deployment",
    )
    assert await service.update_deployment(
        deployment.ref,
        updated_connection.ref,
        {"model_id": "turbo"},
        TTSCapabilities(),
        service.concurrency_token(enabled),
        "alice",
        "update-deployment",
    ) == updated
    with pytest.raises(ManagedResourcePreconditionFailed):
        await service.disable_deployment(
            deployment.ref,
            service.concurrency_token(enabled),
            "alice",
            "stale-deployment",
        )
    disabled = await service.disable_deployment(
        deployment.ref,
        service.concurrency_token(updated),
        "alice",
        "disable-deployment",
    )
    assert await service.disable_deployment(
        deployment.ref,
        service.concurrency_token(updated),
        "alice",
        "disable-deployment",
    ) == disabled


@pytest.mark.asyncio
async def test_external_validation_runs_after_transaction_and_never_mutates() -> None:
    service, repository, validator = setup_service()
    platform = credential()
    repository.credentials[platform.ref] = platform
    connection = await service.create_connection(
        "eleven", "elevenlabs", platform.ref, {}, "alice", "create"
    )
    enabled_connection = await service.enable_connection(
        connection.ref, service.concurrency_token(connection), "alice", "enable"
    )
    deployment = await service.create_deployment(
        "tts", enabled_connection.ref, DeploymentKind.TTS, {"model_id": "flash"},
        TTSCapabilities(), "alice", "deployment"
    )
    enabled_deployment = await service.enable_deployment(
        deployment.ref, service.concurrency_token(deployment), "alice", "enable-deployment"
    )

    assert (await service.validate_connection(enabled_connection.ref)).usable
    assert (await service.validate_deployment(enabled_deployment.ref)).usable
    assert validator.secrets == ["transient-secret", "transient-secret"]
    assert await service.get_connection(enabled_connection.ref) == enabled_connection
    assert await service.get_deployment(enabled_deployment.ref) == enabled_deployment


def test_capability_transport_union_is_exact_and_closed() -> None:
    base: dict[str, Any] = {
        "key": "deployment",
        "connection_ref": str(uuid4()),
        "deployment_config": {},
    }
    values = (
        ("llm", {"kind": "llm", "supports_temperature": True, "supports_reasoning_effort": False}),
        ("realtime", {"kind": "realtime", "supports_server_vad": True, "supports_semantic_vad": False}),
        ("stt", {"kind": "stt", "supports_cascade": True, "supports_realtime_input_transcription": False}),
        ("tts", {"kind": "tts"}),
    )
    for kind, capabilities in values:
        assert ModelDeploymentCreate.model_validate(
            {**base, "deployment_kind": kind, "capabilities": capabilities}
        ).capabilities.kind == kind
    with pytest.raises(ValidationError):
        ModelDeploymentCreate.model_validate(
            {**base, "deployment_kind": "tts", "capabilities": {"kind": "tts", "unknown": True}}
        )
