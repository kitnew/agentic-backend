from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from control_plane.application.command_support import IdempotencyRepository
from control_plane.application.ports.repositories import PlatformRepository
from control_plane.application.ports.transactions import PlatformCommandScope

from .idempotency import SqlAlchemyIdempotencyRepository
from .platform_catalogs import SqlAlchemyPlatformRepository


def platform_configuration_command_scope(
    sessions: async_sessionmaker[AsyncSession],
) -> PlatformCommandScope:
    @asynccontextmanager
    async def transaction() -> AsyncIterator[
        tuple[PlatformRepository, IdempotencyRepository]
    ]:
        async with sessions.begin() as session:
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext('platform_configuration'))")
            )
            yield (
                cast(PlatformRepository, SqlAlchemyPlatformRepository(session)),
                SqlAlchemyIdempotencyRepository(session),
            )

    return transaction
