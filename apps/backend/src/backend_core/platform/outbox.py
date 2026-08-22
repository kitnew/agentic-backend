import asyncio
import json
import logging
import time
from contextlib import nullcontext, suppress
from datetime import UTC, datetime, timedelta

from agentic_observability.propagation import extract_trace_context
from contracts import CapabilityInvocationStatus
from opentelemetry.trace import Tracer
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select

from backend_core.platform.database import Database
from backend_core.runtime.capabilities.models import CapabilityInvocation, OutboxMessage
from backend_core.runtime.capabilities.retention import CapabilityRetentionService

logger = logging.getLogger(__name__)


class OutboxDispatcher:
    def __init__(
        self,
        database: Database,
        redis: Redis,
        stream: str,
        interval_seconds: float,
        consumer_group: str = "capability-workers",
        dead_letter_stream: str | None = None,
        invocation_retention_seconds: int = 30 * 24 * 60 * 60,
        outbox_retention_seconds: int = 7 * 24 * 60 * 60,
        stream_maxlen: int = 10_000,
        maintenance_interval_seconds: int = 3600,
        tracer: Tracer | None = None,
    ) -> None:
        self._database = database
        self._redis = redis
        self._stream = stream
        self._consumer_group = consumer_group
        self._dead_letter_stream = dead_letter_stream or f"{stream}:dead-letter"
        self._interval = interval_seconds
        self._invocation_retention = timedelta(seconds=invocation_retention_seconds)
        self._outbox_retention = timedelta(seconds=outbox_retention_seconds)
        self._stream_maxlen = stream_maxlen
        self._maintenance_interval = maintenance_interval_seconds
        self._tracer = tracer
        self._last_maintenance = 0.0
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
                if (
                    time.monotonic() - self._last_maintenance
                    >= self._maintenance_interval
                ):
                    await self.maintenance_once()
                    self._last_maintenance = time.monotonic()
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
                    stream = message.stream or self._stream
                    scope = (
                        self._tracer.start_as_current_span(
                            "messaging.outbox.send",
                            context=extract_trace_context(message.transport_metadata),
                            attributes={
                                "messaging.system": "redis",
                                "messaging.destination.name": stream,
                            },
                        )
                        if self._tracer is not None
                        else nullcontext()
                    )
                    with scope:
                        await self._redis.xadd(
                            stream,
                            {
                                message.payload_field: json.dumps(
                                    message.payload, separators=(",", ":")
                                ),
                                **{
                                    key: value
                                    for key, value in message.transport_metadata.items()
                                    if key in {"traceparent", "tracestate"}
                                },
                            },
                        )
                except RedisError as error:
                    message.attempts += 1
                    message.last_error = type(error).__name__[:255]
                    continue
                now = datetime.now(UTC)
                message.dispatched_at = now
                message.attempts += 1
                message.last_error = None
                invocation = (
                    await session.get(
                        CapabilityInvocation,
                        message.capability_invocation_id,
                    )
                    if message.capability_invocation_id is not None
                    else None
                )
                if (
                    invocation is not None
                    and invocation.status is CapabilityInvocationStatus.PENDING
                ):
                    invocation.status = CapabilityInvocationStatus.QUEUED
                    invocation.queued_at = now
                dispatched += 1
                logger.info(
                    "capability_job_queued"
                    if invocation is not None
                    else "outbox_message_dispatched",
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
                        "runtime_bundle_id": str(invocation.runtime_bundle_id)
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

    async def maintenance_once(self) -> tuple[int, int]:
        async with self._database.transaction() as session:
            result = await CapabilityRetentionService(session).purge_once(
                invocation_retention=self._invocation_retention,
                outbox_retention=self._outbox_retention,
            )
        await self._trim_streams()
        return result

    async def _trim_streams(self) -> None:
        try:
            pending = await self._redis.xpending(self._stream, self._consumer_group)
            pending_count = (
                pending["pending"] if isinstance(pending, dict) else pending[0]
            )
            if pending_count == 0:
                await self._redis.xtrim(
                    self._stream, maxlen=self._stream_maxlen, approximate=True
                )
            await self._redis.xtrim(
                self._dead_letter_stream,
                maxlen=self._stream_maxlen,
                approximate=True,
            )
        except RedisError:
            logger.exception("capability Redis retention maintenance failed")
