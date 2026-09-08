from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from control_plane.application.command_support import (
    IdempotencyKeyReused,
    opaque_concurrency_token,
    request_fingerprint,
    secret_request_fingerprint,
)
from control_plane.application.ports.transactions import CredentialCommandScope
from control_plane.domain.managed_resource_errors import (
    InvalidManagedResource,
    ManagedResourceConflict,
    ManagedResourcePreconditionFailed,
)
from control_plane.domain.managed_resources import (
    Credential,
    CredentialRef,
    CredentialScope,
    CredentialStatus,
    PlatformCredentialScope,
    TenantCredentialScope,
)

CREATE_OPERATION = "credential.create"
ROTATE_OPERATION = "credential.rotate"
REVOKE_OPERATION = "credential.revoke"


class CredentialService:
    def __init__(self, command_scope: CredentialCommandScope) -> None:
        self._command_scope = command_scope

    async def create(
        self,
        scope: CredentialScope,
        name: str,
        secret: str,
        principal: str,
        idempotency_key: str,
    ) -> Credential:
        scope = self._scope(scope)
        name = name.strip()
        if not name:
            raise InvalidManagedResource("credential name must not be blank")
        fingerprint = secret_request_fingerprint(
            {"scope": self._scope_payload(scope), "name": name}, secret
        )
        async with self._command_scope() as (repository, replays):
            replay = await replays.get(principal, CREATE_OPERATION, idempotency_key)
            if replay is not None:
                return self._replay(
                    replay.request_fingerprint, fingerprint, replay.logical_result
                )
            credential = await repository.create(scope, name, secret, principal)
            await replays.add(
                principal,
                CREATE_OPERATION,
                idempotency_key,
                fingerprint,
                self._result(credential),
            )
        return credential

    async def rotate(
        self,
        ref: CredentialRef,
        secret: str,
        expected_token: str,
        principal: str,
        idempotency_key: str,
    ) -> Credential:
        fingerprint = secret_request_fingerprint(
            {"id": str(ref.value), "if_match": expected_token}, secret
        )
        async with self._command_scope() as (repository, replays):
            replay = await replays.get(principal, ROTATE_OPERATION, idempotency_key)
            if replay is not None:
                return self._replay(
                    replay.request_fingerprint, fingerprint, replay.logical_result
                )
            current = await repository.get(ref, lock=True)
            self._check_precondition(current, expected_token)
            if current.status is CredentialStatus.REVOKED:
                raise ManagedResourceConflict("revoked credential cannot be rotated")
            credential = await repository.rotate(current, secret, principal)
            await replays.add(
                principal,
                ROTATE_OPERATION,
                idempotency_key,
                fingerprint,
                self._result(credential),
            )
        return credential

    async def revoke(
        self,
        ref: CredentialRef,
        expected_token: str,
        principal: str,
        idempotency_key: str,
    ) -> Credential:
        fingerprint = request_fingerprint(
            {"id": str(ref.value), "if_match": expected_token}
        )
        async with self._command_scope() as (repository, replays):
            replay = await replays.get(principal, REVOKE_OPERATION, idempotency_key)
            if replay is not None:
                return self._replay(
                    replay.request_fingerprint, fingerprint, replay.logical_result
                )
            current = await repository.get(ref, lock=True)
            self._check_precondition(current, expected_token)
            if current.status is CredentialStatus.REVOKED:
                raise ManagedResourceConflict("credential is already revoked")
            if await repository.has_enabled_provider_connections(current.ref):
                raise ManagedResourceConflict(
                    "credential is referenced by an enabled provider connection"
                )
            if await repository.has_enabled_integration_connections(current.ref):
                raise ManagedResourceConflict(
                    "credential is referenced by an enabled integration connection"
                )
            credential = await repository.revoke(current, principal)
            await replays.add(
                principal,
                REVOKE_OPERATION,
                idempotency_key,
                fingerprint,
                self._result(credential),
            )
        return credential

    async def get(self, ref: CredentialRef) -> Credential:
        async with self._command_scope() as (repository, _):
            return await repository.get(ref)

    async def list(self, scope: CredentialScope | None = None) -> list[Credential]:
        if scope is not None:
            scope = self._scope(scope)
        async with self._command_scope() as (repository, _):
            return list(await repository.list(scope))

    @staticmethod
    def concurrency_token(credential: Credential) -> str:
        return opaque_concurrency_token(
            {"id": str(credential.ref.value), "generation": credential.generation}
        )

    def _check_precondition(self, credential: Credential, expected_token: str) -> None:
        if self.concurrency_token(credential) != expected_token:
            raise ManagedResourcePreconditionFailed("credential precondition failed")

    @staticmethod
    def _scope(scope: CredentialScope) -> CredentialScope:
        if isinstance(scope, TenantCredentialScope):
            tenant_id = scope.tenant_id.strip()
            if not tenant_id:
                raise InvalidManagedResource(
                    "tenant credential scope requires tenant_id"
                )
            return TenantCredentialScope(tenant_id)
        if isinstance(scope, PlatformCredentialScope):
            return scope
        raise InvalidManagedResource("unsupported credential scope")

    @staticmethod
    def _scope_payload(scope: CredentialScope) -> dict[str, str]:
        if isinstance(scope, TenantCredentialScope):
            return {"type": "tenant", "tenant_id": scope.tenant_id}
        return {"type": "platform"}

    def _result(self, credential: Credential) -> dict[str, Any]:
        return {
            "id": str(credential.ref.value),
            "scope": self._scope_payload(credential.scope),
            "name": credential.name,
            "active_version_id": str(credential.active_version_id),
            "active_secret_version": credential.active_secret_version_number,
            "status": credential.status.value,
            "generation": credential.generation,
            "created_at": credential.created_at.isoformat(),
            "created_by": credential.created_by,
            "revoked_at": (
                credential.revoked_at.isoformat() if credential.revoked_at else None
            ),
            "revoked_by": credential.revoked_by,
        }

    def _replay(
        self, stored_fingerprint: str, fingerprint: str, result: dict[str, Any]
    ) -> Credential:
        if stored_fingerprint != fingerprint:
            raise IdempotencyKeyReused(
                "idempotency key reused with a different request"
            )
        scope_payload = result["scope"]
        scope: CredentialScope = (
            TenantCredentialScope(scope_payload["tenant_id"])
            if scope_payload["type"] == "tenant"
            else PlatformCredentialScope()
        )
        return Credential(
            CredentialRef(UUID(result["id"])),
            scope,
            result["name"],
            UUID(result["active_version_id"]),
            result["active_secret_version"],
            CredentialStatus(result["status"]),
            result["generation"],
            datetime.fromisoformat(result["created_at"]),
            result["created_by"],
            datetime.fromisoformat(result["revoked_at"])
            if result["revoked_at"]
            else None,
            result["revoked_by"],
        )
