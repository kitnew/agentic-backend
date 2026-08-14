from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend_core.modules.calls.models import CallSession, CallSessionStatus


@dataclass(frozen=True)
class StaleRuntimeCall:
    id: UUID
    status: CallSessionStatus
    room_name: str


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
        existing = await self._existing_for(call)
        if existing is not None:
            return existing, False
        try:
            async with self._session.begin_nested():
                self._session.add(call)
                await self._session.flush()
        except IntegrityError:
            existing = await self._existing_for(call)
            if existing is None:
                raise
            return existing, False
        return call, True

    async def _existing_for(self, call: CallSession) -> CallSession | None:
        if call.sip_call_id is not None:
            existing = await self.get_by_sip_call(
                call.provider, call.sip_call_id, call.sip_call_id_full
            )
            if existing is not None:
                return existing
        return await self.get_by_provider_call(call.provider, call.provider_call_id)

    async def get_by_sip_call(
        self,
        provider: str,
        sip_call_id: str,
        sip_call_id_full: str | None,
    ) -> CallSession | None:
        identities = [CallSession.sip_call_id == sip_call_id]
        if sip_call_id_full is not None:
            identities.append(CallSession.sip_call_id_full == sip_call_id_full)
        return await self._session.scalar(
            select(CallSession).where(
                CallSession.provider == provider,
                or_(*identities),
            )
        )

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

    async def list_stale_runtime_calls(
        self, cutoff: datetime, limit: int
    ) -> list[StaleRuntimeCall]:
        rows = await self._session.execute(
            select(CallSession.id, CallSession.status, CallSession.room_name)
            .where(
                or_(
                    and_(
                        CallSession.status == CallSessionStatus.STARTED,
                        CallSession.started_at <= cutoff,
                    ),
                    and_(
                        CallSession.status == CallSessionStatus.CONNECTED,
                        CallSession.connected_at <= cutoff,
                    ),
                )
            )
            .order_by(CallSession.started_at)
            .limit(limit)
        )
        return [StaleRuntimeCall(*row) for row in rows.tuples()]

    async def count_active(self) -> int:
        value = await self._session.scalar(
            select(func.count())
            .select_from(CallSession)
            .where(
                CallSession.status.in_(
                    [CallSessionStatus.STARTED, CallSessionStatus.CONNECTED]
                )
            )
        )
        return int(value or 0)

    async def flush(self) -> None:
        await self._session.flush()
