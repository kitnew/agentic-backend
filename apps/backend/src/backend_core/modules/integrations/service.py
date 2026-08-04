from uuid import UUID

from sqlalchemy.exc import IntegrityError

from backend_core.modules.integrations.models import IntegrationConnection
from backend_core.modules.integrations.repository import IntegrationConnectionRepository
from backend_core.modules.integrations.schemas import (
    CreateIntegrationConnectionRequest,
    UpdateIntegrationConnectionRequest,
)
from backend_core.modules.tenants.repository import TenantRepository


class IntegrationConnectionError(ValueError):
    pass


class IntegrationConnectionService:
    def __init__(
        self,
        tenants: TenantRepository,
        connections: IntegrationConnectionRepository,
    ) -> None:
        self._tenants = tenants
        self._connections = connections

    async def create(
        self, tenant_id: UUID, data: CreateIntegrationConnectionRequest
    ) -> IntegrationConnection:
        if await self._tenants.get(tenant_id) is None:
            raise IntegrationConnectionError("tenant_not_found")
        try:
            return await self._connections.add(
                IntegrationConnection(tenant_id=tenant_id, **data.model_dump())
            )
        except IntegrityError as error:
            raise IntegrationConnectionError("connection_key_conflict") from error

    async def list(self, tenant_id: UUID) -> list[IntegrationConnection]:
        if await self._tenants.get(tenant_id) is None:
            raise IntegrationConnectionError("tenant_not_found")
        return await self._connections.list(tenant_id)

    async def update(
        self,
        tenant_id: UUID,
        connection_id: UUID,
        data: UpdateIntegrationConnectionRequest,
    ) -> IntegrationConnection:
        connection = await self._connections.get_for_update(tenant_id, connection_id)
        if connection is None:
            raise IntegrationConnectionError("connection_not_found")
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(connection, field, value)
        await self._connections.flush()
        await self._connections.refresh(connection)
        return connection
