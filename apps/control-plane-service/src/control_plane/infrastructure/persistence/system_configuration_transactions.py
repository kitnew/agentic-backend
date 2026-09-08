from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from control_plane.application.command_support import IdempotencyRepository
from control_plane.application.ports.repositories import SystemConfigurationRepository
from control_plane.application.ports.transactions import SystemConfigurationCommandScope
from control_plane.infrastructure.encryption import CredentialCipher

from .idempotency import SqlAlchemyIdempotencyRepository
from .live_components import SqlAlchemyLiveComponentRepository
from .providers import SqlAlchemyProviderRepository


class SqlAlchemySystemConfigurationRepository(SqlAlchemyLiveComponentRepository):
    def __init__(self, session: AsyncSession, cipher: CredentialCipher) -> None:
        super().__init__(session)
        self._providers = SqlAlchemyProviderRepository(session, cipher)

    async def get_deployment(self, *args, **kwargs):
        return await self._providers.get_deployment(*args, **kwargs)

    async def get_connection(self, *args, **kwargs):
        return await self._providers.get_connection(*args, **kwargs)

    async def get_credential(self, *args, **kwargs):
        return await self._providers.get_credential(*args, **kwargs)


def system_configuration_command_scope(
    sessions: async_sessionmaker[AsyncSession], cipher: CredentialCipher
) -> SystemConfigurationCommandScope:
    @asynccontextmanager
    async def transaction() -> AsyncIterator[
        tuple[SystemConfigurationRepository, IdempotencyRepository]
    ]:
        async with sessions.begin() as session:
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext('system_configuration'))")
            )
            yield (
                SqlAlchemySystemConfigurationRepository(session, cipher),
                SqlAlchemyIdempotencyRepository(session),
            )

    return transaction
