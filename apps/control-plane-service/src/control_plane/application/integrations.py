from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from control_plane.application.command_support import (
    IdempotencyKeyReused,
    StoredReplay,
    opaque_concurrency_token,
    request_fingerprint,
)
from control_plane.application.ports.repositories import IntegrationRepository
from control_plane.application.ports.transactions import IntegrationCommandScope
from control_plane.domain.components import ComponentAddress, TenantScope
from control_plane.domain.frozen_components import ActionsDefinition
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
    IntegrationConnection,
    IntegrationConnectionRef,
    TenantCredentialScope,
)
from control_plane.domain.registries import IntegrationKindRegistry


@dataclass(frozen=True, slots=True)
class IntegrationValidationResult:
    valid: bool
    usable: bool
    code: str | None = None
    message: str | None = None


class IntegrationService:
    def __init__(
        self, command_scope: IntegrationCommandScope, kinds: IntegrationKindRegistry
    ) -> None:
        self._command_scope = command_scope
        self._kinds = kinds

    async def create(
        self,
        tenant_id: str,
        key: str,
        integration_kind: str,
        config: object,
        credential_ref: CredentialRef | None,
        principal: str,
        idempotency_key: str,
    ) -> IntegrationConnection:
        key = self._key(key)
        config = self._kinds.validate_config(integration_kind, config)
        fingerprint = request_fingerprint(
            {
                "tenant_id": tenant_id,
                "key": key,
                "integration_kind": integration_kind,
                "config": config,
                "credential_ref": str(credential_ref.value) if credential_ref else None,
            }
        )
        async with self._command_scope() as (repository, replays):
            replay = await replays.get(principal, "integration.create", idempotency_key)
            if replay is not None:
                return self._replay(replay, fingerprint)
            if credential_ref is not None:
                credential = await self._credential(repository, credential_ref)
                self._require_tenant_credential(credential, tenant_id, usable=False)
            value = await repository.create(
                tenant_id, key, integration_kind, config, credential_ref, principal
            )
            await replays.add(
                principal,
                "integration.create",
                idempotency_key,
                fingerprint,
                self._result(value),
            )
        return value

    async def update(
        self,
        tenant_id: str,
        ref: IntegrationConnectionRef,
        config: object,
        credential_ref: CredentialRef | None,
        expected_token: str,
        principal: str,
        idempotency_key: str,
    ) -> IntegrationConnection:
        fingerprint = request_fingerprint(
            {
                "tenant_id": tenant_id,
                "id": str(ref.value),
                "config": config,
                "credential_ref": str(credential_ref.value) if credential_ref else None,
                "if_match": expected_token,
            }
        )
        async with self._command_scope() as (repository, replays):
            replay = await replays.get(principal, "integration.update", idempotency_key)
            if replay is not None:
                return self._replay(replay, fingerprint)
            current = await repository.get(ref, lock=True)
            self._require_tenant(current, tenant_id)
            self._check_precondition(current, expected_token)
            validated = self._kinds.validate_config(current.integration_kind, config)
            if credential_ref is not None:
                credential = await self._credential(
                    repository, credential_ref, lock=current.enabled
                )
                self._require_tenant_credential(
                    credential, tenant_id, usable=current.enabled
                )
            value = await repository.update(
                current, validated, credential_ref, principal
            )
            await replays.add(
                principal,
                "integration.update",
                idempotency_key,
                fingerprint,
                self._result(value),
            )
        return value

    async def enable(
        self,
        tenant_id: str,
        ref: IntegrationConnectionRef,
        expected_token: str,
        principal: str,
        idempotency_key: str,
    ) -> IntegrationConnection:
        return await self._set_enabled(
            tenant_id, ref, True, expected_token, principal, idempotency_key
        )

    async def disable(
        self,
        tenant_id: str,
        ref: IntegrationConnectionRef,
        expected_token: str,
        principal: str,
        idempotency_key: str,
    ) -> IntegrationConnection:
        return await self._set_enabled(
            tenant_id, ref, False, expected_token, principal, idempotency_key
        )

    async def _set_enabled(
        self,
        tenant_id: str,
        ref: IntegrationConnectionRef,
        enabled: bool,
        expected_token: str,
        principal: str,
        idempotency_key: str,
    ) -> IntegrationConnection:
        operation = f"integration.{'enable' if enabled else 'disable'}"
        fingerprint = request_fingerprint(
            {"tenant_id": tenant_id, "id": str(ref.value), "if_match": expected_token}
        )
        async with self._command_scope() as (repository, replays):
            replay = await replays.get(principal, operation, idempotency_key)
            if replay is not None:
                return self._replay(replay, fingerprint)
            current = await repository.get(ref, lock=True)
            self._require_tenant(current, tenant_id)
            self._check_precondition(current, expected_token)
            if current.enabled == enabled:
                raise ManagedResourceConflict(
                    f"integration connection is already {'enabled' if enabled else 'disabled'}"
                )
            if enabled:
                self._kinds.validate_config(current.integration_kind, current.config)
                if current.credential_ref is not None:
                    credential = await self._credential(
                        repository, current.credential_ref, lock=True
                    )
                    self._require_tenant_credential(credential, tenant_id, usable=True)
            value = await repository.set_enabled(current, enabled, principal)
            await replays.add(
                principal, operation, idempotency_key, fingerprint, self._result(value)
            )
        return value

    async def get(
        self, tenant_id: str, ref: IntegrationConnectionRef
    ) -> IntegrationConnection:
        async with self._command_scope() as (repository, _):
            value = await repository.get(ref)
            self._require_tenant(value, tenant_id)
            return value

    async def list(self, tenant_id: str) -> list[IntegrationConnection]:
        async with self._command_scope() as (repository, _):
            return list(await repository.list(tenant_id))

    async def validate(
        self, tenant_id: str, ref: IntegrationConnectionRef
    ) -> IntegrationValidationResult:
        async with self._command_scope() as (repository, _):
            value = await repository.get(ref)
            self._require_tenant(value, tenant_id)
            if value.credential_ref is not None:
                credential = await self._credential(repository, value.credential_ref)
                self._require_tenant_credential(credential, tenant_id, usable=True)
        self._kinds.validate_config(value.integration_kind, value.config)
        return IntegrationValidationResult(True, value.enabled)

    async def require_semantic_reference(self, tenant_id: str, key: str) -> None:
        async with self._command_scope() as (repository, _):
            await repository.get_by_key(tenant_id, key)

    async def validate_actions_definition(
        self, address: ComponentAddress, value: object
    ) -> None:
        if not isinstance(value, ActionsDefinition):
            return
        if not isinstance(address.scope, TenantScope):
            raise InvalidManagedResource("ActionsDefinition must be tenant-scoped")
        async with self._command_scope() as (repository, _):
            for action in value.actions.values():
                try:
                    await repository.get_by_key(
                        address.scope.tenant_id, action.execution.integration_key
                    )
                except ManagedResourceNotFound as error:
                    raise InvalidManagedResource(
                        f"integration_key {action.execution.integration_key} does not belong to tenant"
                    ) from error

    @staticmethod
    def concurrency_token(value: IntegrationConnection) -> str:
        return opaque_concurrency_token(
            {"id": str(value.ref.value), "generation": value.generation}
        )

    @staticmethod
    def _key(value: str) -> str:
        value = value.strip()
        if not value or len(value) > 255:
            raise InvalidManagedResource("key must be between 1 and 255 characters")
        return value

    @staticmethod
    async def _credential(
        repository: IntegrationRepository, ref: CredentialRef, *, lock: bool = False
    ) -> Credential:
        try:
            return await repository.get_credential(ref, lock=lock)
        except ManagedResourceNotFound as error:
            raise InvalidManagedResource(
                "referenced credential does not exist"
            ) from error

    @staticmethod
    def _require_tenant_credential(
        credential: Credential, tenant_id: str, *, usable: bool
    ) -> None:
        if (
            not isinstance(credential.scope, TenantCredentialScope)
            or credential.scope.tenant_id != tenant_id
        ):
            raise InvalidManagedResource(
                "integration requires a credential owned by the same tenant"
            )
        if usable and credential.status is CredentialStatus.REVOKED:
            raise InvalidManagedResource("integration credential is revoked")

    @staticmethod
    def _require_tenant(value: IntegrationConnection, tenant_id: str) -> None:
        if value.tenant_id != tenant_id:
            raise ManagedResourceNotFound(
                f"integration connection {value.ref.value} not found"
            )

    def _check_precondition(self, value: IntegrationConnection, token: str) -> None:
        if self.concurrency_token(value) != token:
            raise ManagedResourcePreconditionFailed("resource precondition failed")

    @staticmethod
    def _result(value: IntegrationConnection) -> dict[str, Any]:
        return {
            "id": str(value.ref.value),
            "tenant_id": value.tenant_id,
            "key": value.key,
            "integration_kind": value.integration_kind,
            "config": value.config,
            "credential_ref": str(value.credential_ref.value)
            if value.credential_ref
            else None,
            "enabled": value.enabled,
            "generation": value.generation,
            "created_at": value.created_at.isoformat(),
            "created_by": value.created_by,
            "updated_at": value.updated_at.isoformat(),
            "updated_by": value.updated_by,
        }

    def _replay(self, replay: StoredReplay, fingerprint: str) -> IntegrationConnection:
        if replay.request_fingerprint != fingerprint:
            raise IdempotencyKeyReused(
                "idempotency key reused with a different request"
            )
        value = replay.logical_result
        credential = value["credential_ref"]
        return IntegrationConnection(
            IntegrationConnectionRef(UUID(value["id"])),
            value["tenant_id"],
            value["key"],
            value["integration_kind"],
            value["config"],
            CredentialRef(UUID(credential)) if credential else None,
            value["enabled"],
            value["generation"],
            datetime.fromisoformat(value["created_at"]),
            value["created_by"],
            datetime.fromisoformat(value["updated_at"]),
            value["updated_by"],
        )
