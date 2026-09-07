from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from control_plane.application.ports.transactions import CredentialCommandScope
from control_plane.infrastructure.encryption import CredentialCipher

from .credentials import SqlAlchemyCredentialRepository
from .idempotency import SqlAlchemyIdempotencyRepository


def credential_command_scope(
    sessions: async_sessionmaker[AsyncSession], cipher: CredentialCipher
) -> CredentialCommandScope:
    @asynccontextmanager
    async def transaction() -> AsyncIterator[
        tuple[SqlAlchemyCredentialRepository, SqlAlchemyIdempotencyRepository]
    ]:
        async with sessions.begin() as session:
            yield (
                SqlAlchemyCredentialRepository(session, cipher),
                SqlAlchemyIdempotencyRepository(session),
            )

    return transaction
