from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime

from contracts import ConfigurationComponentPublishedV1
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from control_plane.application.ports.messaging import MessagePublisher, OutboundMessage
from control_plane.infrastructure.persistence.models import OutboxMessage

logger = logging.getLogger(__name__)


class OutboxRelay:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        publisher: MessagePublisher,
        poll_interval_seconds: float = 1.0,
    ) -> None:
        self._sessions = sessions
        self._publisher = publisher
        self._poll_interval_seconds = poll_interval_seconds
        self._stopping = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def ready(self) -> bool:
        return (
            self._task is not None
            and not self._task.done()
            and not self._stopping.is_set()
        )

    async def start(self) -> None:
        if self.ready:
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._run(), name="control-plane-outbox-relay")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stopping.set()
        await self._task
        self._task = None

    async def relay_once(self) -> bool:
        earlier = aliased(OutboxMessage)
        async with self._sessions.begin() as session:
            row = await session.scalar(
                select(OutboxMessage)
                .where(
                    OutboxMessage.published_at.is_(None),
                    ~exists(
                        select(1).where(
                            earlier.component_id == OutboxMessage.component_id,
                            earlier.published_at.is_(None),
                            earlier.revision_number < OutboxMessage.revision_number,
                        )
                    ),
                )
                .order_by(OutboxMessage.created_at, OutboxMessage.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                return False
            event = ConfigurationComponentPublishedV1.model_validate(row.payload)
            row.attempt_count += 1
            try:
                await self._publisher.publish(
                    OutboundMessage(row.subject, event.to_bytes(), str(row.id))
                )
            except Exception as exc:
                row.last_error = str(exc)[:2000]
                logger.warning("Outbox publication failed", exc_info=True)
            else:
                row.published_at = datetime.now(UTC)
                row.last_error = None
            return True

    async def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                worked = await self.relay_once()
            except Exception:
                logger.exception("Outbox relay iteration failed")
                worked = False
            if not worked:
                with suppress(TimeoutError):
                    await asyncio.wait_for(
                        self._stopping.wait(), timeout=self._poll_interval_seconds
                    )
