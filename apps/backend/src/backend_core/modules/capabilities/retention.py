from datetime import UTC, datetime, timedelta

from contracts import CapabilityInvocationStatus
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend_core.modules.capabilities.models import CapabilityInvocation, OutboxMessage


class CapabilityRetentionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def purge_once(
        self,
        *,
        invocation_retention: timedelta,
        outbox_retention: timedelta,
    ) -> tuple[int, int]:
        now = datetime.now(UTC)
        invocation_cutoff = now - invocation_retention
        outbox_cutoff = now - outbox_retention
        terminal = (
            CapabilityInvocationStatus.SUCCEEDED,
            CapabilityInvocationStatus.FAILED,
            CapabilityInvocationStatus.EXPIRED,
        )
        invocation_result = await self._session.execute(
            update(CapabilityInvocation)
            .where(
                CapabilityInvocation.status.in_(terminal),
                CapabilityInvocation.completed_at < invocation_cutoff,
                CapabilityInvocation.pii_purged_at.is_(None),
            )
            .values(
                canonical_input={},
                execution_plan={},
                pii_purged_at=now,
            )
        )
        outbox_result = await self._session.execute(
            delete(OutboxMessage).where(
                OutboxMessage.dispatched_at.is_not(None),
                OutboxMessage.dispatched_at < outbox_cutoff,
            )
        )
        return (
            int(getattr(invocation_result, "rowcount", 0) or 0),
            int(getattr(outbox_result, "rowcount", 0) or 0),
        )
