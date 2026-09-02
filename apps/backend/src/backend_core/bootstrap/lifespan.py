import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from agentic_observability.bootstrap import TelemetryProviders, bootstrap
from agentic_observability.config import TelemetryConfig
from agentic_observability.domain import CoreMetrics
from contracts import CommandResult, MessageEnvelope
from fastapi import FastAPI
from redis.asyncio import Redis

from backend_core.bootstrap.instrumentation import (
    instrument_app,
    instrument_redis_client,
)
from backend_core.modules.calls.reconciliation import CallRuntimeReconciler
from backend_core.modules.calls.repository import CallSessionRepository
from backend_core.modules.tenants.platform_release_repository import (
    PlatformReleaseRepository,
)
from backend_core.modules.tenants.platform_release_service import (
    PlatformReleaseUseCases,
)
from backend_core.modules.tenants.telephony import PlatformTelephonyReconciler
from backend_core.platform.messaging import (
    FINALIZATION_EVENT_GROUP,
    FINALIZATION_RESULT_GROUP,
    TransactionalOutboxBus,
)
from backend_core.platform.outbox import OutboxDispatcher
from backend_core.platform.stream_consumer import RedisStreamConsumer
from backend_core.runtime.execution_context import ExecutionContextReader
from backend_core.runtime.finalization.recording import RecordingCoordinator
from backend_core.runtime.finalization.service import FinalizationService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    telemetry: TelemetryProviders | None = None
    tracer = None
    metrics = None
    if app.state.settings.otel_enabled:
        telemetry = bootstrap(
            TelemetryConfig.from_env(default_service_name="backend-core")
        )
        tracer = telemetry.tracer(__name__)
        meter = telemetry.meter(__name__)
        metrics = CoreMetrics(meter) if meter is not None else None
        if (
            telemetry.tracer_provider is not None
            and telemetry.meter_provider is not None
        ):
            instrument_app(app, telemetry)
            app.state.livekit.instrument_http(
                telemetry.tracer_provider, telemetry.meter_provider
            )
    app.state.outbox_tracer = tracer
    app.state.core_metrics = metrics
    async with app.state.database.transaction() as session:
        await PlatformReleaseUseCases(
            PlatformReleaseRepository(session)
        ).ensure_initial_drafts()
    if metrics is not None:
        async with app.state.database.transaction() as session:
            metrics.set_active_calls(
                await CallSessionRepository(session).count_active()
            )
    await app.state.livekit.start()
    redis: Redis | None = None
    dispatcher: OutboxDispatcher | None = None
    consumers: list[RedisStreamConsumer] = []
    reconciliation_task: asyncio.Task[None] | None = None
    telephony_reconciliation_task: asyncio.Task[None] | None = None
    if app.state.settings.outbox_dispatch_enabled:
        redis = Redis.from_url(
            str(app.state.settings.redis_url),
            decode_responses=True,
            socket_timeout=None,
        )
        if (
            telemetry is not None
            and telemetry.tracer_provider is not None
            and telemetry.meter_provider is not None
        ):
            instrument_redis_client(redis, telemetry)
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
            tracer,
        )
        dispatcher.start()

        async def handle_event(fields: dict[str, str]) -> None:
            event = MessageEnvelope.model_validate_json(fields["message"])
            if (
                event.message_type == "call.started"
                and app.state.settings.call_recording_enabled
            ):
                await RecordingCoordinator(
                    app.state.database,
                    app.state.livekit,
                    event_stream=app.state.settings.domain_event_stream,
                    command_stream=app.state.settings.command_stream,
                    tracer=tracer,
                ).ensure(event.correlation_id)
                return
            if event.message_type not in {
                "call.ended",
                "recording.ready",
                "recording.failed",
            }:
                return
            async with app.state.database.transaction() as session:
                finalization = FinalizationService(
                    session,
                    TransactionalOutboxBus(
                        session,
                        app.state.settings.domain_event_stream,
                        app.state.settings.command_stream,
                        tracer,
                    ),
                    tracer,
                    ExecutionContextReader(app.state.control_plane),
                    app.state.control_plane,
                )
                if event.message_type == "call.ended":
                    await finalization.start(event)
                else:
                    await finalization.recording_changed(event)

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
                        tracer,
                    ),
                    tracer,
                    ExecutionContextReader(app.state.control_plane),
                    app.state.control_plane,
                ).handle_result(envelope, result)

        consumers = [
            RedisStreamConsumer(
                redis,
                app.state.settings.domain_event_stream,
                FINALIZATION_EVENT_GROUP,
                "backend-finalization",
                handle_event,
                tracer=tracer,
            ),
            RedisStreamConsumer(
                redis,
                app.state.settings.command_result_stream,
                FINALIZATION_RESULT_GROUP,
                "backend-finalization-results",
                handle_result,
                tracer=tracer,
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
                recording_enabled=app.state.settings.call_recording_enabled,
                tracer=tracer,
                metrics=metrics,
            ).run(app.state.settings.call_runtime_reconciliation_interval_seconds)
        )
    if app.state.settings.telephony_reconciliation_enabled:
        telephony_reconciliation_task = asyncio.create_task(
            PlatformTelephonyReconciler(
                app.state.database,
                app.state.livekit,
                app.state.settings,
                tracer=tracer,
                metrics=metrics,
            ).run(app.state.settings.telephony_reconciliation_interval_seconds)
        )
    logger.info("Backend Core started")

    try:
        yield
    finally:
        await app.state.control_plane.aclose()
        if reconciliation_task is not None:
            reconciliation_task.cancel()
            with suppress(asyncio.CancelledError):
                await reconciliation_task
        if telephony_reconciliation_task is not None:
            telephony_reconciliation_task.cancel()
            with suppress(asyncio.CancelledError):
                await telephony_reconciliation_task
        for consumer in consumers:
            await consumer.close()
        if dispatcher is not None:
            await dispatcher.close()
        if redis is not None:
            await redis.aclose()
        if telemetry is not None:
            telemetry.shutdown()
        await app.state.livekit.aclose()
        await app.state.database.close()
        logger.info("Backend Core stopped")
