from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend_core.modules.integrations.models import (
    IntegrationConnection,
    IntegrationCredential,
    IntegrationCredentialStatus,
)
from backend_core.modules.tenants.release_models import RuntimeBundleRecord
from backend_core.runtime.capabilities.models import CapabilityInvocation


class IntegrationConnectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, connection: IntegrationConnection) -> IntegrationConnection:
        self._session.add(connection)
        await self._session.flush()
        return connection

    async def get(
        self, tenant_id: UUID, connection_id: UUID
    ) -> IntegrationConnection | None:
        return await self._session.scalar(
            select(IntegrationConnection).where(
                IntegrationConnection.tenant_id == tenant_id,
                IntegrationConnection.id == connection_id,
            )
        )

    async def get_by_key(
        self, tenant_id: UUID, key: str
    ) -> IntegrationConnection | None:
        return await self._session.scalar(
            select(IntegrationConnection).where(
                IntegrationConnection.tenant_id == tenant_id,
                IntegrationConnection.key == key,
            )
        )

    async def get_by_key_for_update(self, tenant_id: UUID, key: str) -> IntegrationConnection | None:
        return await self._session.scalar(
            select(IntegrationConnection)
            .where(IntegrationConnection.tenant_id == tenant_id, IntegrationConnection.key == key)
            .with_for_update()
        )

    async def is_referenced(self, integration_id: UUID) -> bool:
        invocation = await self._session.scalar(
            select(IntegrationConnection.id)
            .join(
                CapabilityInvocation,
                CapabilityInvocation.execution_plan["integration_id"].astext == str(integration_id),
            )
            .where(IntegrationConnection.id == integration_id)
            .limit(1)
        )
        if invocation is not None:
            return True
        return await self._session.scalar(
            select(RuntimeBundleRecord.id).where(
                RuntimeBundleRecord.provenance.contains(
                    {"integration_connection_ids": [str(integration_id)]}
                )
            ).limit(1)
        ) is not None

    async def get_for_update(
        self, tenant_id: UUID, connection_id: UUID
    ) -> IntegrationConnection | None:
        return await self._session.scalar(
            select(IntegrationConnection)
            .where(
                IntegrationConnection.tenant_id == tenant_id,
                IntegrationConnection.id == connection_id,
            )
            .with_for_update()
        )

    async def list(self, tenant_id: UUID) -> list[IntegrationConnection]:
        return list(
            await self._session.scalars(
                select(IntegrationConnection)
                .where(IntegrationConnection.tenant_id == tenant_id)
                .order_by(IntegrationConnection.created_at, IntegrationConnection.id)
            )
        )

    async def flush(self) -> None:
        await self._session.flush()

    async def refresh(self, connection: IntegrationConnection) -> None:
        await self._session.refresh(connection)

    async def delete(self, connection: IntegrationConnection) -> None:
        await self._session.delete(connection)
        await self._session.flush()

    async def active_credential(
        self, integration_id: UUID, *, for_update: bool = False
    ) -> IntegrationCredential | None:
        statement = select(IntegrationCredential).where(
            IntegrationCredential.integration_id == integration_id,
            IntegrationCredential.status == IntegrationCredentialStatus.ACTIVE,
        )
        if for_update:
            statement = statement.with_for_update()
        return await self._session.scalar(statement)

    async def add_credential(self, credential: IntegrationCredential) -> None:
        self._session.add(credential)
        await self._session.flush()
