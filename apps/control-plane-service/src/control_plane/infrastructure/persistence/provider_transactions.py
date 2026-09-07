from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from control_plane.application.ports.transactions import ProviderCommandScope
from control_plane.infrastructure.encryption import CredentialCipher

from .idempotency import SqlAlchemyIdempotencyRepository
from .providers import SqlAlchemyProviderRepository


def provider_command_scope(
    sessions: async_sessionmaker[AsyncSession], cipher: CredentialCipher
) -> ProviderCommandScope:
    @asynccontextmanager
    async def transaction() -> AsyncIterator[
        tuple[SqlAlchemyProviderRepository, SqlAlchemyIdempotencyRepository]
    ]:
        async with sessions.begin() as session:
            yield (
                SqlAlchemyProviderRepository(session, cipher),
                SqlAlchemyIdempotencyRepository(session),
            )

    return transaction
