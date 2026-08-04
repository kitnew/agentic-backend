from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend_core.modules.calls.models import CallSession


class CallSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, call: CallSession) -> CallSession:
        self._session.add(call)
        await self._session.flush()
        return call

    async def get(self, call_id: UUID) -> CallSession | None:
        return await self._session.get(CallSession, call_id)

    async def add_or_get(
        self,
        call: CallSession,
    ) -> tuple[CallSession, bool]:
        existing = await self.get_by_provider_call(
            call.provider,
            call.provider_call_id,
        )
        if existing is not None:
            return existing, False
        try:
            async with self._session.begin_nested():
                self._session.add(call)
                await self._session.flush()
        except IntegrityError:
            existing = await self.get_by_provider_call(
                call.provider,
                call.provider_call_id,
            )
            if existing is None:
                raise
            return existing, False
        return call, True

    async def get_by_provider_call(
        self,
        provider: str,
        provider_call_id: str,
    ) -> CallSession | None:
        return await self._session.scalar(
            select(CallSession).where(
                CallSession.provider == provider,
                CallSession.provider_call_id == provider_call_id,
            )
        )

    async def get_by_admin_idempotency_key(
        self,
        key: str,
    ) -> CallSession | None:
        return await self._session.scalar(
            select(CallSession).where(CallSession.admin_idempotency_key == key)
        )

    async def get_for_update(self, call_id: UUID) -> CallSession | None:
        return await self._session.scalar(
            select(CallSession).where(CallSession.id == call_id).with_for_update()
        )

    async def flush(self) -> None:
        await self._session.flush()
