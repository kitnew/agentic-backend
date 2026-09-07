from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from control_plane.domain.managed_resource_errors import (
    ManagedResourceConflict,
    ManagedResourceNotFound,
)
from control_plane.domain.managed_resources import (
    Credential,
    CredentialRef,
    CredentialScope,
    CredentialStatus,
    DeploymentCapabilities,
    DeploymentKind,
    ModelDeployment,
    ModelDeploymentRef,
    PlatformCredentialScope,
    ProviderConnection,
    ProviderConnectionRef,
    TenantCredentialScope,
    capabilities_from_payload,
    capabilities_payload,
)
from control_plane.infrastructure.encryption import CredentialCipher

from .models import Credential as CredentialRow
from .models import CredentialVersion as CredentialVersionRow
from .models import ModelDeployment as ModelDeploymentRow
from .models import ProviderConnection as ProviderConnectionRow


class SqlAlchemyProviderRepository:
    def __init__(self, session: AsyncSession, cipher: CredentialCipher) -> None:
        self._session = session
        self._cipher = cipher

    async def create_connection(
        self,
        key: str,
        provider_kind: str,
        credential_ref: CredentialRef,
        config: dict[str, object],
        actor: str,
    ) -> ProviderConnection:
        row = ProviderConnectionRow(
            key=key,
            provider_kind=provider_kind,
            credential_id=credential_ref.value,
            connection_config=config,
            enabled=False,
            generation=1,
            created_by=actor,
            updated_by=actor,
        )
        self._session.add(row)
        await self._flush()
        await self._session.refresh(row)
        return self._connection(row)

    async def update_connection(
        self,
        connection: ProviderConnection,
        credential_ref: CredentialRef,
        config: dict[str, object],
        actor: str,
    ) -> ProviderConnection:
        row = await self._connection_row(connection.ref)
        row.credential_id = credential_ref.value
        row.connection_config = config
        row.generation += 1
        row.updated_at = func.now()
        row.updated_by = actor
        await self._flush()
        await self._session.refresh(row)
        return self._connection(row)

    async def set_connection_enabled(
        self, connection: ProviderConnection, enabled: bool, actor: str
    ) -> ProviderConnection:
        row = await self._connection_row(connection.ref)
        row.enabled = enabled
        row.generation += 1
        row.updated_at = func.now()
        row.updated_by = actor
        await self._flush()
        await self._session.refresh(row)
        return self._connection(row)

    async def get_connection(
        self, ref: ProviderConnectionRef, *, lock: bool = False
    ) -> ProviderConnection:
        return self._connection(await self._connection_row(ref, lock=lock))

    async def list_connections(self) -> Sequence[ProviderConnection]:
        rows = (
            await self._session.scalars(
                select(ProviderConnectionRow).order_by(ProviderConnectionRow.key)
            )
        ).all()
        return [self._connection(row) for row in rows]

    async def create_deployment(
        self,
        key: str,
        connection_ref: ProviderConnectionRef,
        kind: DeploymentKind,
        config: dict[str, object],
        capabilities: DeploymentCapabilities,
        actor: str,
    ) -> ModelDeployment:
        row = ModelDeploymentRow(
            key=key,
            connection_id=connection_ref.value,
            deployment_kind=kind.value,
            deployment_config=config,
            capabilities=capabilities_payload(capabilities),
            enabled=False,
            generation=1,
            created_by=actor,
            updated_by=actor,
        )
        self._session.add(row)
        await self._flush()
        await self._session.refresh(row)
        return self._deployment(row)

    async def update_deployment(
        self,
        deployment: ModelDeployment,
        connection_ref: ProviderConnectionRef,
        config: dict[str, object],
        capabilities: DeploymentCapabilities,
        actor: str,
    ) -> ModelDeployment:
        row = await self._deployment_row(deployment.ref)
        row.connection_id = connection_ref.value
        row.deployment_config = config
        row.capabilities = capabilities_payload(capabilities)
        row.generation += 1
        row.updated_at = func.now()
        row.updated_by = actor
        await self._flush()
        await self._session.refresh(row)
        return self._deployment(row)

    async def set_deployment_enabled(
        self, deployment: ModelDeployment, enabled: bool, actor: str
    ) -> ModelDeployment:
        row = await self._deployment_row(deployment.ref)
        row.enabled = enabled
        row.generation += 1
        row.updated_at = func.now()
        row.updated_by = actor
        await self._flush()
        await self._session.refresh(row)
        return self._deployment(row)

    async def get_deployment(
        self, ref: ModelDeploymentRef, *, lock: bool = False
    ) -> ModelDeployment:
        return self._deployment(await self._deployment_row(ref, lock=lock))

    async def list_deployments(self) -> Sequence[ModelDeployment]:
        rows = (
            await self._session.scalars(
                select(ModelDeploymentRow).order_by(ModelDeploymentRow.key)
            )
        ).all()
        return [self._deployment(row) for row in rows]

    async def has_enabled_deployments(self, ref: ProviderConnectionRef) -> bool:
        return (
            await self._session.scalar(
                select(ModelDeploymentRow.id)
                .where(
                    ModelDeploymentRow.connection_id == ref.value,
                    ModelDeploymentRow.enabled.is_(True),
                )
                .limit(1)
            )
            is not None
        )

    async def get_credential(
        self, ref: CredentialRef, *, lock: bool = False
    ) -> Credential:
        row = await self._session.get(
            CredentialRow, ref.value, with_for_update=lock
        )
        if row is None:
            raise ManagedResourceNotFound(f"credential {ref.value} not found")
        if row.active_version_id is None:
            raise ManagedResourceConflict("credential has no active secret version")
        number = await self._session.scalar(
            select(CredentialVersionRow.version_number).where(
                CredentialVersionRow.id == row.active_version_id
            )
        )
        if number is None:
            raise ManagedResourceConflict("credential has no active secret version")
        scope: CredentialScope = (
            TenantCredentialScope(row.tenant_id)
            if row.scope_type == "tenant" and row.tenant_id is not None
            else PlatformCredentialScope()
        )
        return Credential(
            CredentialRef(row.id),
            scope,
            row.name,
            row.active_version_id,
            number,
            CredentialStatus(row.status),
            row.generation,
            row.created_at,
            row.created_by,
            row.revoked_at,
            row.revoked_by,
        )

    async def credential_secret(self, credential: Credential) -> str:
        if credential.status is CredentialStatus.REVOKED:
            raise ManagedResourceConflict("revoked credential cannot be materialized")
        row = await self._session.get(
            CredentialVersionRow, credential.active_version_id
        )
        if row is None or row.retired_at is not None:
            raise ManagedResourceConflict("credential has no active secret version")
        return self._cipher.decrypt(
            credential.ref.value,
            row.version_number,
            row.nonce,
            row.ciphertext,
            row.key_id,
            row.algorithm,
        )

    async def _connection_row(
        self, ref: ProviderConnectionRef, *, lock: bool = False
    ) -> ProviderConnectionRow:
        row = await self._session.get(
            ProviderConnectionRow, ref.value, with_for_update=lock
        )
        if row is None:
            raise ManagedResourceNotFound(f"provider connection {ref.value} not found")
        return row

    async def _deployment_row(
        self, ref: ModelDeploymentRef, *, lock: bool = False
    ) -> ModelDeploymentRow:
        row = await self._session.get(
            ModelDeploymentRow, ref.value, with_for_update=lock
        )
        if row is None:
            raise ManagedResourceNotFound(f"model deployment {ref.value} not found")
        return row

    async def _flush(self) -> None:
        try:
            await self._session.flush()
        except IntegrityError as error:
            raise ManagedResourceConflict(
                "managed resource constraint conflict"
            ) from error

    @staticmethod
    def _connection(row: ProviderConnectionRow) -> ProviderConnection:
        return ProviderConnection(
            ProviderConnectionRef(row.id),
            row.key,
            row.provider_kind,
            CredentialRef(row.credential_id),
            dict(row.connection_config),
            row.enabled,
            row.generation,
            row.created_at,
            row.created_by,
            row.updated_at,
            row.updated_by,
        )

    @staticmethod
    def _deployment(row: ModelDeploymentRow) -> ModelDeployment:
        return ModelDeployment(
            ModelDeploymentRef(row.id),
            row.key,
            ProviderConnectionRef(row.connection_id),
            DeploymentKind(row.deployment_kind),
            dict(row.deployment_config),
            capabilities_from_payload(dict(row.capabilities)),
            row.enabled,
            row.generation,
            row.created_at,
            row.created_by,
            row.updated_at,
            row.updated_by,
        )
