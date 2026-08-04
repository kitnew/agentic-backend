import asyncio
import json
import logging
from contextlib import suppress
from datetime import UTC, datetime

from contracts import CapabilityInvocationStatus
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select

from backend_core.modules.capabilities.models import CapabilityInvocation, OutboxMessage
from backend_core.platform.database import Database

logger = logging.getLogger(__name__)


class OutboxDispatcher:
    def __init__(
        self,
        database: Database,
        redis: Redis,
        stream: str,
        interval_seconds: float,
    ) -> None:
        self._database = database
        self._redis = redis
        self._stream = stream
        self._interval = interval_seconds
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="capability-outbox")

    async def close(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task

    async def _run(self) -> None:
        while True:
            try:
                await self.dispatch_once()
            except Exception:
                logger.exception("capability outbox dispatch failed")
            await asyncio.sleep(self._interval)

    async def dispatch_once(self) -> int:
        dispatched = 0
        async with self._database.transaction() as session:
            messages = list(
                await session.scalars(
                    select(OutboxMessage)
                    .where(OutboxMessage.dispatched_at.is_(None))
                    .order_by(OutboxMessage.created_at)
                    .limit(20)
                    .with_for_update(skip_locked=True)
                )
            )
            for message in messages:
                try:
                    await self._redis.xadd(
                        self._stream,
                        {"job": json.dumps(message.payload, separators=(",", ":"))},
                    )
                except RedisError as error:
                    message.attempts += 1
                    message.last_error = type(error).__name__[:255]
                    continue
                now = datetime.now(UTC)
                message.dispatched_at = now
                message.attempts += 1
                message.last_error = None
                invocation = await session.get(
                    CapabilityInvocation,
                    message.capability_invocation_id,
                )
                if (
                    invocation is not None
                    and invocation.status is CapabilityInvocationStatus.PENDING
                ):
                    invocation.status = CapabilityInvocationStatus.QUEUED
                    invocation.queued_at = now
                dispatched += 1
                logger.info(
                    "capability_job_queued",
                    extra={
                        "invocation_id": str(message.capability_invocation_id),
                        "job_id": str(message.job_id),
                        "tenant_id": str(invocation.tenant_id)
                        if invocation is not None
                        else None,
                        "call_id": str(invocation.call_id)
                        if invocation is not None
                        else None,
                        "semantic_key": invocation.semantic_key
                        if invocation is not None
                        else None,
                        "semantic_version": invocation.semantic_version
                        if invocation is not None
                        else None,
                        "tenant_config_revision_id": str(
                            invocation.tenant_config_revision_id
                        )
                        if invocation is not None
                        else None,
                        "plan_type": invocation.execution_plan.get("plan_type")
                        if invocation is not None
                        else None,
                        "status": "queued",
                        "latency_ms": round(
                            (now - message.created_at).total_seconds() * 1000
                        ),
                    },
                )
        return dispatched
