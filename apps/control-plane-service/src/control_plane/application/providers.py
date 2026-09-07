from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from control_plane.application.command_support import (
    IdempotencyKeyReused,
    StoredReplay,
    opaque_concurrency_token,
    request_fingerprint,
)
from control_plane.application.ports.repositories import ProviderRepository
from control_plane.application.ports.transactions import ProviderCommandScope
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
    DeploymentCapabilities,
    DeploymentKind,
    ModelDeployment,
    ModelDeploymentRef,
    PlatformCredentialScope,
    ProviderConnection,
    ProviderConnectionRef,
    capabilities_from_payload,
    capabilities_payload,
)
from control_plane.domain.registries import (
    DeploymentKindRegistry,
    ProviderKindRegistry,
    UnknownRegistryKey,
)


@dataclass(frozen=True, slots=True)
class ProviderValidationResult:
    valid: bool
    usable: bool
    code: str | None = None
    message: str | None = None


class ProviderValidator(Protocol):
    async def validate_connection(
        self,
        provider_kind: str,
        connection_config: dict[str, object],
        secret: str,
    ) -> ProviderValidationResult: ...

    async def validate_deployment(
        self,
        provider_kind: str,
        connection_config: dict[str, object],
        deployment_kind: DeploymentKind,
        deployment_config: dict[str, object],
        secret: str,
    ) -> ProviderValidationResult: ...


class ProviderService:
    def __init__(
        self,
        command_scope: ProviderCommandScope,
        provider_kinds: ProviderKindRegistry,
        deployment_kinds: DeploymentKindRegistry,
        validator: ProviderValidator,
    ) -> None:
        self._command_scope = command_scope
        self._provider_kinds = provider_kinds
        self._deployment_kinds = deployment_kinds
        self._validator = validator

    async def create_connection(
        self,
        key: str,
        provider_kind: str,
        credential_ref: CredentialRef,
        connection_config: object,
        principal: str,
        idempotency_key: str,
    ) -> ProviderConnection:
        key = self._key(key)
        config = self._provider_kinds.validate_connection(
            provider_kind, connection_config
        )
        fingerprint = request_fingerprint(
            {
                "key": key,
                "provider_kind": provider_kind,
                "credential_ref": str(credential_ref.value),
                "connection_config": config,
            }
        )
        async with self._command_scope() as (repository, replays):
            replay = await replays.get(
                principal, "provider_connection.create", idempotency_key
            )
            if replay is not None:
                return self._connection_replay(replay, fingerprint)
            credential = await self._referenced_credential(repository, credential_ref)
            self._require_platform_credential(credential, usable=False)
            value = await repository.create_connection(
                key, provider_kind, credential_ref, config, principal
            )
            await replays.add(
                principal,
                "provider_connection.create",
                idempotency_key,
                fingerprint,
                self._connection_result(value),
            )
        return value

    async def update_connection(
        self,
        ref: ProviderConnectionRef,
        credential_ref: CredentialRef,
        connection_config: object,
        expected_token: str,
        principal: str,
        idempotency_key: str,
    ) -> ProviderConnection:
        fingerprint = request_fingerprint(
            {
                "id": str(ref.value),
                "credential_ref": str(credential_ref.value),
                "connection_config": connection_config,
                "if_match": expected_token,
            }
        )
        async with self._command_scope() as (repository, replays):
            replay = await replays.get(
                principal, "provider_connection.update", idempotency_key
            )
            if replay is not None:
                return self._connection_replay(replay, fingerprint)
            current = await repository.get_connection(ref, lock=True)
            self._check_precondition(current, expected_token)
            config = self._provider_kinds.validate_connection(
                current.provider_kind, connection_config
            )
            credential = await self._referenced_credential(
                repository, credential_ref, lock=current.enabled
            )
            self._require_platform_credential(credential, usable=current.enabled)
            value = await repository.update_connection(
                current, credential_ref, config, principal
            )
            await replays.add(
                principal,
                "provider_connection.update",
                idempotency_key,
                fingerprint,
                self._connection_result(value),
            )
        return value

    async def enable_connection(
        self,
        ref: ProviderConnectionRef,
        expected_token: str,
        principal: str,
        idempotency_key: str,
    ) -> ProviderConnection:
        return await self._set_connection_enabled(
            ref, True, expected_token, principal, idempotency_key
        )

    async def disable_connection(
        self,
        ref: ProviderConnectionRef,
        expected_token: str,
        principal: str,
        idempotency_key: str,
    ) -> ProviderConnection:
        return await self._set_connection_enabled(
            ref, False, expected_token, principal, idempotency_key
        )

    async def _set_connection_enabled(
        self,
        ref: ProviderConnectionRef,
        enabled: bool,
        expected_token: str,
        principal: str,
        idempotency_key: str,
    ) -> ProviderConnection:
        operation = f"provider_connection.{'enable' if enabled else 'disable'}"
        fingerprint = request_fingerprint(
            {"id": str(ref.value), "if_match": expected_token}
        )
        async with self._command_scope() as (repository, replays):
            replay = await replays.get(principal, operation, idempotency_key)
            if replay is not None:
                return self._connection_replay(replay, fingerprint)
            current = await repository.get_connection(ref, lock=True)
            self._check_precondition(current, expected_token)
            if current.enabled == enabled:
                raise ManagedResourceConflict(
                    f"provider connection is already {'enabled' if enabled else 'disabled'}"
                )
            if enabled:
                credential = await repository.get_credential(
                    current.credential_ref, lock=True
                )
                self._require_platform_credential(credential, usable=True)
                self._provider_kinds.validate_connection(
                    current.provider_kind, current.connection_config
                )
            elif await repository.has_enabled_deployments(current.ref):
                raise ManagedResourceConflict(
                    "provider connection is referenced by an enabled model deployment"
                )
            value = await repository.set_connection_enabled(
                current, enabled, principal
            )
            await replays.add(
                principal,
                operation,
                idempotency_key,
                fingerprint,
                self._connection_result(value),
            )
        return value

    async def get_connection(self, ref: ProviderConnectionRef) -> ProviderConnection:
        async with self._command_scope() as (repository, _):
            return await repository.get_connection(ref)

    async def list_connections(self) -> list[ProviderConnection]:
        async with self._command_scope() as (repository, _):
            return list(await repository.list_connections())

    async def validate_connection(
        self, ref: ProviderConnectionRef
    ) -> ProviderValidationResult:
        async with self._command_scope() as (repository, _):
            connection = await repository.get_connection(ref)
            self._provider_kinds.validate_connection(
                connection.provider_kind, connection.connection_config
            )
            credential = await repository.get_credential(connection.credential_ref)
            self._require_platform_credential(credential, usable=True)
            secret = await repository.credential_secret(credential)
        result = await self._validator.validate_connection(
            connection.provider_kind, connection.connection_config, secret
        )
        return ProviderValidationResult(
            result.valid,
            result.usable and connection.enabled,
            result.code,
            result.message,
        )

    async def create_deployment(
        self,
        key: str,
        connection_ref: ProviderConnectionRef,
        deployment_kind: DeploymentKind,
        deployment_config: object,
        capabilities: DeploymentCapabilities,
        principal: str,
        idempotency_key: str,
    ) -> ModelDeployment:
        key = self._key(key)
        self._validate_capabilities(deployment_kind, capabilities)
        fingerprint = request_fingerprint(
            {
                "key": key,
                "connection_ref": str(connection_ref.value),
                "deployment_kind": deployment_kind.value,
                "deployment_config": deployment_config,
                "capabilities": capabilities_payload(capabilities),
            }
        )
        async with self._command_scope() as (repository, replays):
            replay = await replays.get(
                principal, "model_deployment.create", idempotency_key
            )
            if replay is not None:
                return self._deployment_replay(replay, fingerprint)
            connection = await self._referenced_connection(repository, connection_ref)
            config = self._provider_kinds.validate_deployment(
                connection.provider_kind, deployment_kind, deployment_config
            )
            value = await repository.create_deployment(
                key,
                connection_ref,
                deployment_kind,
                config,
                capabilities,
                principal,
            )
            await replays.add(
                principal,
                "model_deployment.create",
                idempotency_key,
                fingerprint,
                self._deployment_result(value),
            )
        return value

    async def update_deployment(
        self,
        ref: ModelDeploymentRef,
        connection_ref: ProviderConnectionRef,
        deployment_config: object,
        capabilities: DeploymentCapabilities,
        expected_token: str,
        principal: str,
        idempotency_key: str,
    ) -> ModelDeployment:
        fingerprint = request_fingerprint(
            {
                "id": str(ref.value),
                "connection_ref": str(connection_ref.value),
                "deployment_config": deployment_config,
                "capabilities": capabilities_payload(capabilities),
                "if_match": expected_token,
            }
        )
        async with self._command_scope() as (repository, replays):
            replay = await replays.get(
                principal, "model_deployment.update", idempotency_key
            )
            if replay is not None:
                return self._deployment_replay(replay, fingerprint)
            current = await repository.get_deployment(ref, lock=True)
            self._check_precondition(current, expected_token)
            self._validate_capabilities(current.deployment_kind, capabilities)
            connection = await self._referenced_connection(
                repository, connection_ref, lock=current.enabled
            )
            if current.enabled:
                await self._require_usable_connection(repository, connection)
            config = self._provider_kinds.validate_deployment(
                connection.provider_kind,
                current.deployment_kind,
                deployment_config,
            )
            value = await repository.update_deployment(
                current, connection_ref, config, capabilities, principal
            )
            await replays.add(
                principal,
                "model_deployment.update",
                idempotency_key,
                fingerprint,
                self._deployment_result(value),
            )
        return value

    async def enable_deployment(
        self,
        ref: ModelDeploymentRef,
        expected_token: str,
        principal: str,
        idempotency_key: str,
    ) -> ModelDeployment:
        return await self._set_deployment_enabled(
            ref, True, expected_token, principal, idempotency_key
        )

    async def disable_deployment(
        self,
        ref: ModelDeploymentRef,
        expected_token: str,
        principal: str,
        idempotency_key: str,
    ) -> ModelDeployment:
        return await self._set_deployment_enabled(
            ref, False, expected_token, principal, idempotency_key
        )

    async def _set_deployment_enabled(
        self,
        ref: ModelDeploymentRef,
        enabled: bool,
        expected_token: str,
        principal: str,
        idempotency_key: str,
    ) -> ModelDeployment:
        operation = f"model_deployment.{'enable' if enabled else 'disable'}"
        fingerprint = request_fingerprint(
            {"id": str(ref.value), "if_match": expected_token}
        )
        async with self._command_scope() as (repository, replays):
            replay = await replays.get(principal, operation, idempotency_key)
            if replay is not None:
                return self._deployment_replay(replay, fingerprint)
            current = await repository.get_deployment(ref, lock=True)
            self._check_precondition(current, expected_token)
            if current.enabled == enabled:
                raise ManagedResourceConflict(
                    f"model deployment is already {'enabled' if enabled else 'disabled'}"
                )
            if enabled:
                connection = await repository.get_connection(
                    current.connection_ref, lock=True
                )
                await self._require_usable_connection(repository, connection)
                self._provider_kinds.validate_deployment(
                    connection.provider_kind,
                    current.deployment_kind,
                    current.deployment_config,
                )
                self._validate_capabilities(
                    current.deployment_kind, current.capabilities
                )
            value = await repository.set_deployment_enabled(
                current, enabled, principal
            )
            await replays.add(
                principal,
                operation,
                idempotency_key,
                fingerprint,
                self._deployment_result(value),
            )
        return value

    async def get_deployment(self, ref: ModelDeploymentRef) -> ModelDeployment:
        async with self._command_scope() as (repository, _):
            return await repository.get_deployment(ref)

    async def list_deployments(self) -> list[ModelDeployment]:
        async with self._command_scope() as (repository, _):
            return list(await repository.list_deployments())

    async def validate_deployment(
        self, ref: ModelDeploymentRef
    ) -> ProviderValidationResult:
        async with self._command_scope() as (repository, _):
            deployment = await repository.get_deployment(ref)
            connection = await repository.get_connection(deployment.connection_ref)
            await self._require_usable_connection(repository, connection)
            config = self._provider_kinds.validate_deployment(
                connection.provider_kind,
                deployment.deployment_kind,
                deployment.deployment_config,
            )
            self._validate_capabilities(
                deployment.deployment_kind, deployment.capabilities
            )
            credential = await repository.get_credential(connection.credential_ref)
            secret = await repository.credential_secret(credential)
        result = await self._validator.validate_deployment(
            connection.provider_kind,
            connection.connection_config,
            deployment.deployment_kind,
            config,
            secret,
        )
        return ProviderValidationResult(
            result.valid,
            result.usable and deployment.enabled,
            result.code,
            result.message,
        )

    @staticmethod
    def concurrency_token(value: ProviderConnection | ModelDeployment) -> str:
        return opaque_concurrency_token(
            {"id": str(value.ref.value), "generation": value.generation}
        )

    async def _require_usable_connection(
        self, repository: ProviderRepository, connection: ProviderConnection
    ) -> None:
        if not connection.enabled:
            raise InvalidManagedResource("provider connection is disabled")
        credential = await repository.get_credential(
            connection.credential_ref, lock=True
        )
        self._require_platform_credential(credential, usable=True)
        self._provider_kinds.validate_connection(
            connection.provider_kind, connection.connection_config
        )

    @staticmethod
    async def _referenced_credential(
        repository: ProviderRepository, ref: CredentialRef, *, lock: bool = False
    ) -> Credential:
        try:
            return await repository.get_credential(ref, lock=lock)
        except ManagedResourceNotFound as error:
            raise InvalidManagedResource("referenced credential does not exist") from error

    @staticmethod
    async def _referenced_connection(
        repository: ProviderRepository,
        ref: ProviderConnectionRef,
        *,
        lock: bool = False,
    ) -> ProviderConnection:
        try:
            return await repository.get_connection(ref, lock=lock)
        except ManagedResourceNotFound as error:
            raise InvalidManagedResource(
                "referenced provider connection does not exist"
            ) from error

    def _validate_capabilities(
        self, kind: DeploymentKind, capabilities: DeploymentCapabilities
    ) -> None:
        try:
            entry = self._deployment_kinds.resolve(kind.value)
        except UnknownRegistryKey as error:
            raise InvalidManagedResource(str(error)) from error
        if capabilities.kind != entry.metadata["capability_kind"]:
            raise InvalidManagedResource(
                f"capabilities do not match deployment_kind={kind.value}"
            )
        if any(
            type(value) is not bool
            for name, value in capabilities_payload(capabilities).items()
            if name != "kind"
        ):
            raise InvalidManagedResource("capability values must be booleans")

    @staticmethod
    def _require_platform_credential(
        credential: Credential, *, usable: bool
    ) -> None:
        if not isinstance(credential.scope, PlatformCredentialScope):
            raise InvalidManagedResource(
                "provider connection requires a platform credential"
            )
        if usable and credential.status is CredentialStatus.REVOKED:
            raise InvalidManagedResource("provider connection credential is revoked")

    @staticmethod
    def _key(value: str) -> str:
        value = value.strip()
        if not value or len(value) > 255:
            raise InvalidManagedResource("key must be between 1 and 255 characters")
        return value

    def _check_precondition(
        self, value: ProviderConnection | ModelDeployment, expected_token: str
    ) -> None:
        if self.concurrency_token(value) != expected_token:
            raise ManagedResourcePreconditionFailed("resource precondition failed")

    @staticmethod
    def _check_replay(replay: StoredReplay, fingerprint: str) -> dict[str, Any]:
        if replay.request_fingerprint != fingerprint:
            raise IdempotencyKeyReused(
                "idempotency key reused with a different request"
            )
        return replay.logical_result

    @staticmethod
    def _connection_result(value: ProviderConnection) -> dict[str, Any]:
        return {
            "id": str(value.ref.value),
            "key": value.key,
            "provider_kind": value.provider_kind,
            "credential_ref": str(value.credential_ref.value),
            "connection_config": value.connection_config,
            "enabled": value.enabled,
            "generation": value.generation,
            "created_at": value.created_at.isoformat(),
            "created_by": value.created_by,
            "updated_at": value.updated_at.isoformat(),
            "updated_by": value.updated_by,
        }

    def _connection_replay(
        self, replay: StoredReplay, fingerprint: str
    ) -> ProviderConnection:
        value = self._check_replay(replay, fingerprint)
        return ProviderConnection(
            ProviderConnectionRef(UUID(value["id"])),
            value["key"],
            value["provider_kind"],
            CredentialRef(UUID(value["credential_ref"])),
            value["connection_config"],
            value["enabled"],
            value["generation"],
            datetime.fromisoformat(value["created_at"]),
            value["created_by"],
            datetime.fromisoformat(value["updated_at"]),
            value["updated_by"],
        )

    @staticmethod
    def _deployment_result(value: ModelDeployment) -> dict[str, Any]:
        return {
            "id": str(value.ref.value),
            "key": value.key,
            "connection_ref": str(value.connection_ref.value),
            "deployment_kind": value.deployment_kind.value,
            "deployment_config": value.deployment_config,
            "capabilities": capabilities_payload(value.capabilities),
            "enabled": value.enabled,
            "generation": value.generation,
            "created_at": value.created_at.isoformat(),
            "created_by": value.created_by,
            "updated_at": value.updated_at.isoformat(),
            "updated_by": value.updated_by,
        }

    def _deployment_replay(
        self, replay: StoredReplay, fingerprint: str
    ) -> ModelDeployment:
        value = self._check_replay(replay, fingerprint)
        return ModelDeployment(
            ModelDeploymentRef(UUID(value["id"])),
            value["key"],
            ProviderConnectionRef(UUID(value["connection_ref"])),
            DeploymentKind(value["deployment_kind"]),
            value["deployment_config"],
            capabilities_from_payload(value["capabilities"]),
            value["enabled"],
            value["generation"],
            datetime.fromisoformat(value["created_at"]),
            value["created_by"],
            datetime.fromisoformat(value["updated_at"]),
            value["updated_by"],
        )
