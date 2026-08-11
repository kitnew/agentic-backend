from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend_core.modules.integrations.models import IntegrationConnection


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
