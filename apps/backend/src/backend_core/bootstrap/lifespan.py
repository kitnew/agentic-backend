import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from contracts import CommandResult, MessageEnvelope
from fastapi import FastAPI
from redis.asyncio import Redis

from backend_core.modules.calls.reconciliation import CallRuntimeReconciler
from backend_core.platform.messaging import (
    FINALIZATION_EVENT_GROUP,
    FINALIZATION_RESULT_GROUP,
    TransactionalOutboxBus,
)
from backend_core.platform.outbox import OutboxDispatcher
from backend_core.platform.stream_consumer import RedisStreamConsumer
from backend_core.runtime.finalization.service import FinalizationService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await app.state.livekit.start()
    redis: Redis | None = None
    dispatcher: OutboxDispatcher | None = None
    consumers: list[RedisStreamConsumer] = []
    reconciliation_task: asyncio.Task[None] | None = None
    if app.state.settings.outbox_dispatch_enabled:
        redis = Redis.from_url(str(app.state.settings.redis_url), decode_responses=True)
        dispatcher = OutboxDispatcher(
            app.state.database,
            redis,
            app.state.settings.capability_job_stream,
            app.state.settings.outbox_dispatch_interval_seconds,
            app.state.settings.capability_job_consumer_group,
            app.state.settings.capability_job_dead_letter_stream,
            app.state.settings.capability_invocation_pii_retention_seconds,
            app.state.settings.capability_outbox_retention_seconds,
            app.state.settings.capability_stream_maxlen,
            app.state.settings.capability_retention_maintenance_interval_seconds,
        )
        dispatcher.start()

        async def handle_event(fields: dict[str, str]) -> None:
            event = MessageEnvelope.model_validate_json(fields["message"])
            if event.message_type != "call.ended":
                return
            async with app.state.database.transaction() as session:
                await FinalizationService(
                    session,
                    TransactionalOutboxBus(
                        session,
                        app.state.settings.domain_event_stream,
                        app.state.settings.command_stream,
                    ),
                ).start(event)

        async def handle_result(fields: dict[str, str]) -> None:
            envelope = MessageEnvelope.model_validate_json(fields["message"])
            if (
                envelope.message_kind != "command_result"
                or envelope.message_type != "command.result"
            ):
                raise ValueError("message is not a command result")
            result = CommandResult.model_validate(envelope.payload)
            async with app.state.database.transaction() as session:
                await FinalizationService(
                    session,
                    TransactionalOutboxBus(
                        session,
                        app.state.settings.domain_event_stream,
                        app.state.settings.command_stream,
                    ),
                ).handle_result(envelope, result)

        consumers = [
            RedisStreamConsumer(
                redis,
                app.state.settings.domain_event_stream,
                FINALIZATION_EVENT_GROUP,
                "backend-finalization",
                handle_event,
            ),
            RedisStreamConsumer(
                redis,
                app.state.settings.command_result_stream,
                FINALIZATION_RESULT_GROUP,
                "backend-finalization-results",
                handle_result,
            ),
        ]
        for consumer in consumers:
            consumer.start()
    if app.state.settings.call_runtime_reconciliation_enabled:
        reconciliation_task = asyncio.create_task(
            CallRuntimeReconciler(
                app.state.database,
                app.state.livekit,
                grace_seconds=app.state.settings.call_runtime_reconciliation_grace_seconds,
                batch_size=app.state.settings.call_runtime_reconciliation_batch_size,
                event_stream=app.state.settings.domain_event_stream,
                command_stream=app.state.settings.command_stream,
            ).run(app.state.settings.call_runtime_reconciliation_interval_seconds)
        )
    logger.info("Backend Core started")

    try:
        yield
    finally:
        if reconciliation_task is not None:
            reconciliation_task.cancel()
            with suppress(asyncio.CancelledError):
                await reconciliation_task
        for consumer in consumers:
            await consumer.close()
        if dispatcher is not None:
            await dispatcher.close()
        if redis is not None:
            await redis.aclose()
        await app.state.livekit.aclose()
        await app.state.database.close()
        logger.info("Backend Core stopped")
