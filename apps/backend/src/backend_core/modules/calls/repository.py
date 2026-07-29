from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend_core.modules.calls.models import CallSession


class CallSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, call: CallSession) -> CallSession:
        self._session.add(call)
        await self._session.flush()
        return call

    async def get_for_update(self, call_id: UUID) -> CallSession | None:
        return await self._session.scalar(
            select(CallSession)
            .where(CallSession.id == call_id)
            .with_for_update()
        )

    async def flush(self) -> None:
        await self._session.flush()
