from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse
from uuid import UUID, uuid4

from contracts import ExecutionPlan, RuntimeIntegrationMaterial
from contracts.integration import HttpConnectionConfiguration
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.exc import IntegrityError

from backend_core.modules.integrations.crypto import IntegrationSecretCipher
from backend_core.modules.integrations.models import (
    IntegrationConnection,
    IntegrationCredential,
    IntegrationCredentialStatus,
    IntegrationKind,
)
from backend_core.modules.integrations.providers import (
    IntegrationProviderError,
    validate_config,
    validate_secret,
)
from backend_core.modules.integrations.repository import IntegrationConnectionRepository
from backend_core.modules.integrations.schemas import (
    ConfigureIntegrationConnectionRequest,
    CreateIntegrationConnectionRequest,
    IntegrationIssue,
    IntegrationPlan,
    IntegrationPlanChange,
    IntegrationReadiness,
)
from backend_core.modules.tenants.repository import TenantRepository
from backend_core.runtime.capabilities.repository import CapabilityInvocationRepository

_execution_plan: TypeAdapter[ExecutionPlan] = TypeAdapter(ExecutionPlan)


class IntegrationConnectionError(ValueError):
    pass


@dataclass(frozen=True)
class IntegrationConnectionView:
    connection: IntegrationConnection
    credential: IntegrationCredential | None
    readiness: IntegrationReadiness


class IntegrationConnectionService:
    def __init__(self, tenants: TenantRepository, connections: IntegrationConnectionRepository, cipher: IntegrationSecretCipher) -> None:
        self._tenants, self._connections, self._cipher = tenants, connections, cipher

    async def create(self, tenant_id: UUID, data: CreateIntegrationConnectionRequest) -> IntegrationConnectionView:
        if await self._tenants.get(tenant_id) is None:
            raise IntegrationConnectionError("tenant_not_found")
        kind = IntegrationKind(data.kind)
        try:
            connection = await self._connections.add(
                IntegrationConnection(tenant_id=tenant_id, key=data.key, kind=kind, configuration={})
            )
        except IntegrityError as error:
            raise IntegrationConnectionError("integration_conflict") from error
        return self._view(connection, None)

    async def list(self, tenant_id: UUID) -> list[IntegrationConnectionView]:
        if await self._tenants.get(tenant_id) is None:
            raise IntegrationConnectionError("tenant_not_found")
        return [self._view(item, await self._connections.active_credential(item.id)) for item in await self._connections.list(tenant_id)]

    async def get(self, tenant_id: UUID, key: str) -> IntegrationConnectionView:
        connection = await self._connections.get_by_key(tenant_id, key)
        if connection is None:
            raise IntegrationConnectionError("integration_not_found")
        return self._view(connection, await self._connections.active_credential(connection.id))

    async def get_by_id(
        self, tenant_id: UUID, connection_id: UUID
    ) -> IntegrationConnectionView:
        connection = await self._connections.get(tenant_id, connection_id)
        if connection is None:
            raise IntegrationConnectionError("integration_not_found")
        return self._view(connection, await self._connections.active_credential(connection.id))

    async def delete(self, tenant_id: UUID, key: str) -> None:
        connection = await self._connections.get_by_key_for_update(tenant_id, key)
        if connection is None:
            raise IntegrationConnectionError("integration_not_found")
        if await self._connections.is_referenced(connection.id):
            raise IntegrationConnectionError("integration_in_use")
        await self._connections.delete(connection)

    async def configure(self, tenant_id: UUID, key: str, data: ConfigureIntegrationConnectionRequest, expected_revision: int) -> IntegrationConnectionView:
        connection = await self._connections.get_by_key_for_update(tenant_id, key)
        if connection is None:
            raise IntegrationConnectionError("integration_not_found")
        if connection.revision != expected_revision:
            raise IntegrationConnectionError("integration_conflict")
        if connection.kind is not IntegrationKind.HTTP:
            raise IntegrationConnectionError("integration_configuration_invalid")
        credential = await self._connections.active_credential(connection.id, for_update=True)
        if data.credential is not None:
            credential = await self._rotate(connection, credential, data.credential.api_key)
        elif data.configuration.authentication.type == "none" and credential is not None:
            credential.status = IntegrationCredentialStatus.RETIRED
            credential.retired_at = datetime.now(UTC)
            credential = None
        candidate = IntegrationConnection(
            tenant_id=connection.tenant_id, key=connection.key, kind=connection.kind,
            configuration=data.configuration.model_dump(mode="json"), enabled=connection.enabled,
        )
        connection.configuration = candidate.configuration
        connection.revision += 1
        await self._connections.flush()
        await self._connections.refresh(connection)
        return self._view(connection, credential)

    async def plan(self, tenant_id: UUID, key: str, data: ConfigureIntegrationConnectionRequest) -> IntegrationPlan:
        current = await self.get(tenant_id, key)
        candidate = IntegrationConnection(tenant_id=current.connection.tenant_id, key=key, kind=IntegrationKind.HTTP, configuration=data.configuration.model_dump(mode="json"), enabled=current.connection.enabled)
        readiness = self._readiness(
            candidate,
            current.credential,
            supplied=data.credential is not None,
        )
        configuration_issues = [
            issue
            for issue in readiness.issues
            if issue.code not in {"credential_missing", "credential_revoked"}
        ]
        changes = [] if current.connection.configuration == candidate.configuration else [IntegrationPlanChange(path="configuration", operation="replace", before=current.connection.configuration, after=candidate.configuration)]
        return IntegrationPlan(valid=not configuration_issues, changes=changes, issues=configuration_issues, credential="rotate" if data.credential else "unchanged", would_be_ready=readiness.ready)

    async def set_enabled(self, tenant_id: UUID, key: str, enabled: bool) -> IntegrationConnectionView:
        connection = await self._connections.get_by_key_for_update(tenant_id, key)
        if connection is None:
            raise IntegrationConnectionError("integration_not_found")
        credential = await self._connections.active_credential(connection.id)
        if enabled and not self._readiness(connection, credential).ready:
            raise IntegrationConnectionError("integration_not_ready")
        if connection.enabled != enabled:
            connection.enabled = enabled
            connection.revision += 1
            await self._connections.flush()
            await self._connections.refresh(connection)
        return self._view(connection, credential)

    async def update(self, tenant_id: UUID, connection_id: UUID, data: object) -> IntegrationConnectionView:
        connection = await self._connections.get_for_update(tenant_id, connection_id)
        if connection is None:
            raise IntegrationConnectionError("connection_not_found")
        if getattr(data, "status", None) is not None:
            return await self._set_enabled_id(connection, data.status.value == "active")
        return self._view(connection, await self._connections.active_credential(connection.id))

    async def _set_enabled_id(self, connection: IntegrationConnection, enabled: bool) -> IntegrationConnectionView:
        credential = await self._connections.active_credential(connection.id)
        if enabled and not self._readiness(connection, credential).ready:
            raise IntegrationConnectionError("integration_not_ready")
        connection.enabled = enabled
        connection.revision += 1
        await self._connections.flush()
        return self._view(connection, credential)

    async def set_secret(self, tenant_id: UUID, connection_id: UUID, secret: dict[str, object], *, rotate: bool) -> IntegrationConnectionView:
        connection = await self._connections.get_for_update(tenant_id, connection_id)
        if connection is None:
            raise IntegrationConnectionError("connection_not_found")
        current = await self._connections.active_credential(connection.id, for_update=True)
        if current is not None and not rotate:
            raise IntegrationConnectionError("credential_already_configured")
        if connection.kind is IntegrationKind.GOOGLE_SHEETS:
            credential = await self._rotate_secret(connection, current, secret)
        else:
            credential = await self._rotate(connection, current, str(secret.get("api_key", "")))
        return self._view(connection, credential)

    async def _rotate_secret(self, connection: IntegrationConnection, current: IntegrationCredential | None, secret: dict[str, object]) -> IntegrationCredential:
        try:
            validate_secret(connection.kind, secret)
        except IntegrationProviderError as error:
            raise IntegrationConnectionError("credential_invalid") from error
        version = (current.version if current else 0) + 1
        nonce, ciphertext, fingerprint = self._cipher.encrypt(connection.tenant_id, connection.id, version, secret)
        if current is not None:
            current.status = IntegrationCredentialStatus.RETIRED
            current.retired_at = datetime.now(UTC)
        credential = IntegrationCredential(id=uuid4(), tenant_id=connection.tenant_id, integration_id=connection.id, version=version, status=IntegrationCredentialStatus.ACTIVE, nonce=nonce, ciphertext=ciphertext, fingerprint=fingerprint)
        await self._connections.add_credential(credential)
        return credential

    async def revoke_secret(self, tenant_id: UUID, connection_id: UUID) -> IntegrationConnectionView:
        connection = await self._connections.get_for_update(tenant_id, connection_id)
        if connection is None:
            raise IntegrationConnectionError("connection_not_found")
        credential = await self._connections.active_credential(connection.id, for_update=True)
        if credential is None:
            raise IntegrationConnectionError("credential_not_configured")
        credential.status = IntegrationCredentialStatus.REVOKED
        credential.revoked_at = datetime.now(UTC)
        await self._connections.flush()
        return self._view(connection, credential)

    async def test(self, tenant_id: UUID, connection_id: UUID) -> IntegrationConnectionView:
        connection = await self._connections.get(tenant_id, connection_id)
        if connection is None:
            raise IntegrationConnectionError("connection_not_found")
        credential = await self._connections.active_credential(connection.id)
        if not self._readiness(connection, credential).ready:
            raise IntegrationConnectionError("credential_not_configured")
        return self._view(connection, credential)

    async def rotate(self, tenant_id: UUID, key: str, api_key: str) -> IntegrationConnectionView:
        connection = await self._connections.get_by_key_for_update(tenant_id, key)
        if connection is None:
            raise IntegrationConnectionError("integration_not_found")
        credential = await self._connections.active_credential(connection.id, for_update=True)
        credential = await self._rotate(connection, credential, api_key)
        return self._view(connection, credential)

    async def revoke(self, tenant_id: UUID, key: str) -> IntegrationConnectionView:
        connection = await self._connections.get_by_key_for_update(tenant_id, key)
        if connection is None:
            raise IntegrationConnectionError("integration_not_found")
        credential = await self._connections.active_credential(connection.id, for_update=True)
        if credential is None:
            raise IntegrationConnectionError("credential_missing")
        credential.status = IntegrationCredentialStatus.REVOKED
        credential.revoked_at = datetime.now(UTC)
        await self._connections.flush()
        return self._view(connection, credential)

    def material(self, connection: IntegrationConnection, credential: IntegrationCredential | None) -> RuntimeIntegrationMaterial:
        readiness = self._readiness(connection, credential)
        if not connection.enabled:
            raise IntegrationConnectionError("integration_disabled")
        if not readiness.usable:
            raise IntegrationConnectionError("credential_missing")
        secret = None
        credential_version = None
        if readiness.credentials != "not_required":
            if credential is None:
                raise IntegrationConnectionError("credential_missing")
            secret = self._decrypt(connection, credential)
            credential_version = credential.version
        if connection.kind is IntegrationKind.HTTP:
            config = HttpConnectionConfiguration.model_validate(connection.configuration)
            host = urlparse(config.endpoint).hostname
            assert host is not None
            allowed = {host.lower().rstrip(".")} | {item.lower().rstrip(".") for item in config.security.additional_allowed_hosts}
            auth_header = config.authentication.header_name if config.authentication.type == "api_key_header" else None
            return RuntimeIntegrationMaterial(integration_id=connection.id, kind="http", provider="http", endpoint=config.endpoint, static_headers=config.headers, authentication_header=auth_header, allowed_hosts=sorted(allowed), config={}, secret=secret, connection_revision=connection.revision, credential_version=credential_version)
        return RuntimeIntegrationMaterial(integration_id=connection.id, kind="google_sheets", provider="google_sheets", config=connection.configuration, secret=secret, connection_revision=connection.revision, credential_version=credential_version)

    async def _rotate(self, connection: IntegrationConnection, current: IntegrationCredential | None, api_key: str) -> IntegrationCredential:
        try:
            validate_secret(connection.kind, {"api_key": api_key})
        except IntegrationProviderError as error:
            raise IntegrationConnectionError("credential_invalid") from error
        version = (current.version if current else 0) + 1
        nonce, ciphertext, fingerprint = self._cipher.encrypt(connection.tenant_id, connection.id, version, {"api_key": api_key})
        if current is not None:
            current.status = IntegrationCredentialStatus.RETIRED
            current.retired_at = datetime.now(UTC)
        credential = IntegrationCredential(id=uuid4(), tenant_id=connection.tenant_id, integration_id=connection.id, version=version, status=IntegrationCredentialStatus.ACTIVE, nonce=nonce, ciphertext=ciphertext, fingerprint=fingerprint)
        await self._connections.add_credential(credential)
        return credential

    def _decrypt(self, connection: IntegrationConnection, credential: IntegrationCredential) -> dict[str, object]:
        try:
            secret = self._cipher.decrypt(connection.tenant_id, connection.id, credential.version, credential.nonce, credential.ciphertext)
            validate_secret(connection.kind, secret)
            return secret
        except (IntegrationProviderError, ValueError) as error:
            raise IntegrationConnectionError("credential_invalid") from error

    def _view(self, connection: IntegrationConnection, credential: IntegrationCredential | None) -> IntegrationConnectionView:
        return IntegrationConnectionView(connection, credential, self._readiness(connection, credential))

    @staticmethod
    def _readiness(connection: IntegrationConnection, credential: IntegrationCredential | None, *, supplied: bool = False) -> IntegrationReadiness:
        issues: list[IntegrationIssue] = []
        try:
            if connection.kind is IntegrationKind.HTTP:
                HttpConnectionConfiguration.model_validate(connection.configuration)
            else:
                validate_config(connection.kind, connection.configuration)
            configuration = "valid"
        except (ValueError, IntegrationProviderError):
            configuration = "incomplete" if not connection.configuration else "invalid"
            issues.append(IntegrationIssue(code="integration_configuration_invalid", message="configuration is not ready"))
        auth_required = connection.kind is IntegrationKind.GOOGLE_SHEETS or (connection.kind is IntegrationKind.HTTP and connection.configuration.get("authentication", {}).get("type") == "api_key_header")
        if not auth_required:
            credentials, credential_ready = "not_required", True
        elif credential is None and not supplied:
            credentials, credential_ready = "missing", False
            issues.append(IntegrationIssue(code="credential_missing", message="API key is required"))
        elif supplied or (
            credential is not None
            and credential.status is IntegrationCredentialStatus.ACTIVE
        ):
            credentials, credential_ready = "configured", True
        else:
            credentials, credential_ready = "revoked", False
            issues.append(IntegrationIssue(code="credential_revoked", message="credential is not usable"))
        ready = configuration == "valid" and credential_ready
        return IntegrationReadiness(configuration=configuration, credentials=credentials, ready=ready, usable=connection.enabled and ready, issues=issues)


class CapabilityIntegrationResolver:
    def __init__(self, invocations: CapabilityInvocationRepository, connections: IntegrationConnectionRepository, integrations: IntegrationConnectionService) -> None:
        self._invocations, self._connections, self._integrations = invocations, connections, integrations

    async def resolve(self, invocation_id: UUID, job_id: UUID, *, call_id: UUID | None = None, runtime_bundle_id: UUID | None = None) -> RuntimeIntegrationMaterial:
        invocation = await self._invocations.get(invocation_id)
        if invocation is None or invocation.job_id != job_id or (call_id is not None and invocation.call_id != call_id) or (runtime_bundle_id is not None and invocation.runtime_bundle_id != runtime_bundle_id):
            raise IntegrationConnectionError("capability_not_found")
        try:
            plan = _execution_plan.validate_python(invocation.execution_plan)
        except ValidationError as error:
            raise IntegrationConnectionError("capability_plan_invalid") from error
        connection = await self._connections.get(invocation.tenant_id, plan.integration_id)
        if connection is None:
            raise IntegrationConnectionError("connection_not_found")
        credential = await self._connections.active_credential(connection.id)
        return self._integrations.material(connection, credential)
