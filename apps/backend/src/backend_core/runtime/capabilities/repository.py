from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend_core.runtime.capabilities.models import (
    CapabilityConfirmation,
    CapabilityInvocation,
    OutboxMessage,
)


class CapabilityInvocationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self, invocation_id: UUID, *, for_update: bool = False
    ) -> CapabilityInvocation | None:
        query = select(CapabilityInvocation).where(
            CapabilityInvocation.id == invocation_id
        )
        if for_update:
            query = query.with_for_update()
        return await self._session.scalar(query)

    async def get_by_tool_call(
        self, tenant_id: UUID, call_id: UUID, tool_call_id: str
    ) -> CapabilityInvocation | None:
        return await self._session.scalar(
            select(CapabilityInvocation).where(
                CapabilityInvocation.tenant_id == tenant_id,
                CapabilityInvocation.call_id == call_id,
                CapabilityInvocation.tool_call_id == tool_call_id,
            )
        )

    async def add_with_outbox(
        self, invocation: CapabilityInvocation, outbox: OutboxMessage
    ) -> tuple[CapabilityInvocation, bool]:
        try:
            async with self._session.begin_nested():
                self._session.add_all((invocation, outbox))
                await self._session.flush()
            return invocation, True
        except IntegrityError:
            existing = await self.get_by_tool_call(
                invocation.tenant_id, invocation.call_id, invocation.tool_call_id
            )
            if existing is None:
                raise
            return existing, False

    async def flush(self) -> None:
        await self._session.flush()

    async def get_confirmation(
        self, confirmation_id: UUID, *, for_update: bool = False
    ) -> CapabilityConfirmation | None:
        query = select(CapabilityConfirmation).where(
            CapabilityConfirmation.id == confirmation_id
        )
        if for_update:
            query = query.with_for_update()
        return await self._session.scalar(query)

    async def get_confirmation_by_tool_call(
        self, tenant_id: UUID, call_id: UUID, tool_call_id: str
    ) -> CapabilityConfirmation | None:
        return await self._session.scalar(
            select(CapabilityConfirmation).where(
                CapabilityConfirmation.tenant_id == tenant_id,
                CapabilityConfirmation.call_id == call_id,
                CapabilityConfirmation.tool_call_id == tool_call_id,
            )
        )

    async def add_confirmation(
        self, confirmation: CapabilityConfirmation
    ) -> CapabilityConfirmation:
        self._session.add(confirmation)
        await self._session.flush()
        return confirmation
