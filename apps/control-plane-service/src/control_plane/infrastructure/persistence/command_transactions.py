from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from control_plane.application.command_support import IdempotencyRepository
from control_plane.application.ports.repositories import ComponentRepository
from control_plane.application.ports.transactions import ComponentCommandScope

from .idempotency import SqlAlchemyIdempotencyRepository
from .repository import SqlAlchemyComponentRepository


def component_command_scope(
    sessions: async_sessionmaker[AsyncSession],
) -> ComponentCommandScope:
    @asynccontextmanager
    async def transaction() -> AsyncIterator[
        tuple[ComponentRepository, IdempotencyRepository]
    ]:
        async with sessions.begin() as session:
            yield (
                cast(ComponentRepository, SqlAlchemyComponentRepository(session)),
                SqlAlchemyIdempotencyRepository(session),
            )

    return transaction
