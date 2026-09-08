from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from control_plane.application.command_support import IdempotencyRepository
from control_plane.application.ports.repositories import TenantConfigurationRepository
from control_plane.application.ports.transactions import (
    LiveComponentCommandScope,
    TenantConfigurationCommandScope,
)
from control_plane.domain.components import ComponentAddress

from .idempotency import SqlAlchemyIdempotencyRepository
from .integrations import SqlAlchemyIntegrationRepository
from .live_components import SqlAlchemyLiveComponentRepository
from .platform_catalogs import SqlAlchemyPlatformRepository
from .repository import SqlAlchemyComponentRepository


class SqlAlchemyTenantConfigurationRepository(SqlAlchemyComponentRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._live = SqlAlchemyLiveComponentRepository(session)
        self._platform = SqlAlchemyPlatformRepository(session)
        self._integrations = SqlAlchemyIntegrationRepository(session)

    async def get_live(self, *args, **kwargs):
        return await self._live.get(*args, **kwargs)

    async def get(self, *args, **kwargs):
        return await self.get_live(*args, **kwargs)

    async def set_live(self, *args, **kwargs):
        return await self._live.set(*args, **kwargs)

    async def set(self, *args, **kwargs):
        return await self.set_live(*args, **kwargs)

    async def get_profile(self, *args, **kwargs):
        return await self._platform.get_profile(*args, **kwargs)

    async def get_integration_by_key(self, *args, **kwargs):
        return await self._integrations.get_by_key(*args, **kwargs)


def tenant_configuration_command_scope(
    sessions: async_sessionmaker[AsyncSession],
) -> TenantConfigurationCommandScope:
    @asynccontextmanager
    async def transaction(
        tenant_id: str,
    ) -> AsyncIterator[tuple[TenantConfigurationRepository, IdempotencyRepository]]:
        async with sessions.begin() as session:
            await session.execute(
                text(
                    "SELECT pg_advisory_xact_lock("
                    "hashtextextended('tenant_configuration:' || :tenant_id, 0))"
                ),
                {"tenant_id": tenant_id},
            )
            yield (
                cast(
                    TenantConfigurationRepository,
                    SqlAlchemyTenantConfigurationRepository(session),
                ),
                SqlAlchemyIdempotencyRepository(session),
            )

    return transaction


def tenant_live_component_command_scope(
    scope: TenantConfigurationCommandScope,
) -> LiveComponentCommandScope:
    def transaction(address: ComponentAddress):
        tenant_id = address.scope.key
        if tenant_id is None:
            raise ValueError("tenant live component requires tenant scope")
        return scope(tenant_id)

    return transaction
