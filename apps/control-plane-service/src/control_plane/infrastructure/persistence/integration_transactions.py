from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from control_plane.application.ports.transactions import IntegrationCommandScope

from .idempotency import SqlAlchemyIdempotencyRepository
from .integrations import SqlAlchemyIntegrationRepository


def integration_command_scope(
    sessions: async_sessionmaker[AsyncSession],
) -> IntegrationCommandScope:
    @asynccontextmanager
    async def transaction() -> AsyncIterator[
        tuple[SqlAlchemyIntegrationRepository, SqlAlchemyIdempotencyRepository]
    ]:
        async with sessions.begin() as session:
            yield (
                SqlAlchemyIntegrationRepository(session),
                SqlAlchemyIdempotencyRepository(session),
            )

    return transaction
