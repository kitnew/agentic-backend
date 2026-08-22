from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from contracts import ExecutionPlan, RuntimeIntegrationMaterial
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.exc import IntegrityError

from backend_core.modules.integrations.crypto import IntegrationSecretCipher
from backend_core.modules.integrations.models import (
    IntegrationConnection,
    IntegrationConnectionStatus,
    IntegrationCredential,
    IntegrationCredentialStatus,
    IntegrationProvider,
)
from backend_core.modules.integrations.providers import (
    IntegrationProviderError,
    validate_config,
    validate_secret,
)
from backend_core.modules.integrations.repository import IntegrationConnectionRepository
from backend_core.modules.integrations.schemas import (
    CreateIntegrationConnectionRequest,
    UpdateIntegrationConnectionRequest,
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


class IntegrationConnectionService:
    def __init__(
        self,
        tenants: TenantRepository,
        connections: IntegrationConnectionRepository,
        cipher: IntegrationSecretCipher,
    ) -> None:
        self._tenants = tenants
        self._connections = connections
        self._cipher = cipher

    async def create(
        self, tenant_id: UUID, data: CreateIntegrationConnectionRequest
    ) -> IntegrationConnectionView:
        if await self._tenants.get(tenant_id) is None:
            raise IntegrationConnectionError("tenant_not_found")
        try:
            validate_config(data.provider, data.config, allow_empty=True)
            connection = await self._connections.add(
                IntegrationConnection(
                    tenant_id=tenant_id,
                    status=IntegrationConnectionStatus.DISABLED,
                    **data.model_dump(),
                )
            )
        except IntegrationProviderError as error:
            raise IntegrationConnectionError(str(error)) from error
        except IntegrityError as error:
            raise IntegrationConnectionError("connection_key_conflict") from error
        return IntegrationConnectionView(connection, None)

    async def list(self, tenant_id: UUID) -> list[IntegrationConnectionView]:
        if await self._tenants.get(tenant_id) is None:
            raise IntegrationConnectionError("tenant_not_found")
        return [
            IntegrationConnectionView(
                item, await self._connections.active_credential(item.id)
            )
            for item in await self._connections.list(tenant_id)
        ]

    async def get(
        self, tenant_id: UUID, connection_id: UUID
    ) -> IntegrationConnectionView:
        connection = await self._connections.get(tenant_id, connection_id)
        if connection is None:
            raise IntegrationConnectionError("connection_not_found")
        return IntegrationConnectionView(
            connection, await self._connections.active_credential(connection.id)
        )

    async def delete(self, tenant_id: UUID, connection_id: UUID) -> None:
        connection = await self._connections.get_for_update(tenant_id, connection_id)
        if connection is None:
            raise IntegrationConnectionError("connection_not_found")
        await self._connections.delete(connection)

    async def update(
        self,
        tenant_id: UUID,
        connection_id: UUID,
        data: UpdateIntegrationConnectionRequest,
    ) -> IntegrationConnectionView:
        connection = await self._connections.get_for_update(tenant_id, connection_id)
        if connection is None:
            raise IntegrationConnectionError("connection_not_found")
        values = data.model_dump(exclude_unset=True)
        if "config" in values:
            try:
                validate_config(connection.provider, values["config"])
            except IntegrationProviderError as error:
                raise IntegrationConnectionError(str(error)) from error
        for field, value in values.items():
            setattr(connection, field, value)
        if connection.status is IntegrationConnectionStatus.ACTIVE:
            self._validate_ready(
                connection, await self._connections.active_credential(connection.id)
            )
        connection.revision += 1
        await self._connections.flush()
        await self._connections.refresh(connection)
        return IntegrationConnectionView(
            connection, await self._connections.active_credential(connection.id)
        )

    async def set_secret(
        self,
        tenant_id: UUID,
        connection_id: UUID,
        secret: dict[str, object],
        *,
        rotate: bool,
    ) -> IntegrationConnectionView:
        connection = await self._connections.get_for_update(tenant_id, connection_id)
        if connection is None:
            raise IntegrationConnectionError("connection_not_found")
        try:
            validate_secret(connection.provider, secret)
        except IntegrationProviderError as error:
            raise IntegrationConnectionError(str(error)) from error
        current = await self._connections.active_credential(
            connection.id, for_update=True
        )
        if current is not None and not rotate:
            raise IntegrationConnectionError("credential_already_configured")
        if current is None and rotate:
            raise IntegrationConnectionError("credential_not_configured")
        version = (current.version if current is not None else 0) + 1
        nonce, ciphertext, fingerprint = self._cipher.encrypt(
            tenant_id, connection.id, version, secret
        )
        if current is not None:
            current.status = IntegrationCredentialStatus.RETIRED
            current.retired_at = datetime.now(UTC)
        credential = IntegrationCredential(
            id=uuid4(),
            tenant_id=tenant_id,
            integration_id=connection.id,
            version=version,
            status=IntegrationCredentialStatus.ACTIVE,
            nonce=nonce,
            ciphertext=ciphertext,
            fingerprint=fingerprint,
        )
        await self._connections.add_credential(credential)
        connection.revision += 1
        await self._connections.flush()
        await self._connections.refresh(connection)
        return IntegrationConnectionView(connection, credential)

    async def revoke_secret(
        self, tenant_id: UUID, connection_id: UUID
    ) -> IntegrationConnectionView:
        connection = await self._connections.get_for_update(tenant_id, connection_id)
        if connection is None:
            raise IntegrationConnectionError("connection_not_found")
        credential = await self._connections.active_credential(
            connection.id, for_update=True
        )
        if credential is None:
            raise IntegrationConnectionError("credential_not_configured")
        credential.status = IntegrationCredentialStatus.REVOKED
        credential.revoked_at = datetime.now(UTC)
        connection.revision += 1
        await self._connections.flush()
        await self._connections.refresh(connection)
        return IntegrationConnectionView(connection, None)

    async def test(
        self, tenant_id: UUID, connection_id: UUID
    ) -> IntegrationConnectionView:
        view = await self.get(tenant_id, connection_id)
        if view.connection.status is not IntegrationConnectionStatus.ACTIVE:
            raise IntegrationConnectionError("connection_disabled")
        if view.credential is None:
            raise IntegrationConnectionError("credential_not_configured")
        self._validate_ready(view.connection, view.credential)
        self._decrypt(view.connection, view.credential)
        return view

    def material(
        self,
        connection: IntegrationConnection,
        credential: IntegrationCredential,
    ) -> RuntimeIntegrationMaterial:
        if connection.status is not IntegrationConnectionStatus.ACTIVE:
            raise IntegrationConnectionError("connection_disabled")
        if credential.status is not IntegrationCredentialStatus.ACTIVE:
            raise IntegrationConnectionError("credential_not_configured")
        self._validate_ready(connection, credential)
        return RuntimeIntegrationMaterial(
            integration_id=connection.id,
            provider=connection.provider.value,
            config=connection.config,
            secret=self._decrypt(connection, credential),
            credential_version=credential.version,
        )

    def _decrypt(
        self, connection: IntegrationConnection, credential: IntegrationCredential
    ) -> dict[str, object]:
        try:
            secret = self._cipher.decrypt(
                connection.tenant_id,
                connection.id,
                credential.version,
                credential.nonce,
                credential.ciphertext,
            )
            validate_secret(connection.provider, secret)
            return secret
        except (IntegrationProviderError, ValueError) as error:
            raise IntegrationConnectionError("credential_invalid") from error

    def _validate_ready(
        self,
        connection: IntegrationConnection,
        credential: IntegrationCredential | None,
    ) -> None:
        if credential is None:
            raise IntegrationConnectionError("credential_not_configured")
        try:
            validate_config(connection.provider, connection.config)
        except IntegrationProviderError as error:
            raise IntegrationConnectionError(str(error)) from error


class CapabilityIntegrationResolver:
    """Resolves only the integration pinned by an existing capability invocation."""

    def __init__(
        self,
        invocations: CapabilityInvocationRepository,
        connections: IntegrationConnectionRepository,
        integrations: IntegrationConnectionService,
    ) -> None:
        self._invocations = invocations
        self._connections = connections
        self._integrations = integrations

    async def resolve(
        self,
        invocation_id: UUID,
        job_id: UUID,
        *,
        call_id: UUID | None = None,
        runtime_bundle_id: UUID | None = None,
    ) -> RuntimeIntegrationMaterial:
        invocation = await self._invocations.get(invocation_id)
        if invocation is None or invocation.job_id != job_id:
            raise IntegrationConnectionError("capability_not_found")
        if call_id is not None and invocation.call_id != call_id:
            raise IntegrationConnectionError("capability_not_found")
        if runtime_bundle_id is not None and invocation.runtime_bundle_id != runtime_bundle_id:
            raise IntegrationConnectionError("capability_not_found")
        try:
            plan = _execution_plan.validate_python(invocation.execution_plan)
        except ValidationError as error:
            raise IntegrationConnectionError("capability_plan_invalid") from error
        connection = await self._connections.get(
            invocation.tenant_id, plan.integration_id
        )
        if connection is None:
            raise IntegrationConnectionError("connection_not_found")
        expected = IntegrationProvider(plan.plan_type.rsplit(".", 2)[0])
        if connection.provider is not expected:
            raise IntegrationConnectionError("connection_provider_mismatch")
        credential = await self._connections.active_credential(connection.id)
        if credential is None:
            raise IntegrationConnectionError("credential_not_configured")
        return self._integrations.material(connection, credential)
