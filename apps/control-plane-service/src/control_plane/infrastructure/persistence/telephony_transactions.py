from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from control_plane.application.ports.transactions import TelephonyCommandScope

from .idempotency import SqlAlchemyIdempotencyRepository
from .telephony import (
    SqlAlchemyHandoffDestinationRepository,
    SqlAlchemyPhoneNumberAssignmentRepository,
)


def telephony_command_scope(
    sessions: async_sessionmaker[AsyncSession],
) -> TelephonyCommandScope:
    @asynccontextmanager
    async def transaction() -> AsyncIterator[
        tuple[
            SqlAlchemyPhoneNumberAssignmentRepository,
            SqlAlchemyHandoffDestinationRepository,
            SqlAlchemyIdempotencyRepository,
        ]
    ]:
        async with sessions.begin() as session:
            yield (
                SqlAlchemyPhoneNumberAssignmentRepository(session),
                SqlAlchemyHandoffDestinationRepository(session),
                SqlAlchemyIdempotencyRepository(session),
            )

    return transaction
