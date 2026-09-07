from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from control_plane.application.command_support import StoredReplay

from .models import IdempotencyReplay


class SqlAlchemyIdempotencyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self, principal: str, operation: str, idempotency_key: str
    ) -> StoredReplay | None:
        row = await self._session.scalar(
            select(IdempotencyReplay).where(
                IdempotencyReplay.principal == principal,
                IdempotencyReplay.operation == operation,
                IdempotencyReplay.idempotency_key == idempotency_key,
            )
        )
        return (
            StoredReplay(row.request_fingerprint, dict(row.logical_result))
            if row is not None
            else None
        )

    async def add(
        self,
        principal: str,
        operation: str,
        idempotency_key: str,
        fingerprint: str,
        logical_result: dict[str, object],
    ) -> None:
        self._session.add(
            IdempotencyReplay(
                principal=principal,
                operation=operation,
                idempotency_key=idempotency_key,
                request_fingerprint=fingerprint,
                logical_result=logical_result,
            )
        )
        await self._session.flush()
