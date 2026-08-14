from agentic_observability.propagation import inject_trace_context
from contracts import MessageEnvelope
from opentelemetry.trace import Tracer
from sqlalchemy.ext.asyncio import AsyncSession

from backend_core.application.messaging import CommandBus, EventBus
from backend_core.runtime.capabilities.models import OutboxMessage

DOMAIN_EVENT_STREAM = "domain:events"
COMMAND_STREAM = "application:commands"
COMMAND_RESULT_STREAM = "application:command-results"
FINALIZATION_EVENT_GROUP = "backend-finalization"
FINALIZATION_RESULT_GROUP = "backend-finalization-results"
COMMAND_WORKER_GROUP = "job-workers"


class TransactionalOutboxBus(EventBus, CommandBus):
    def __init__(
        self,
        session: AsyncSession,
        event_stream: str = DOMAIN_EVENT_STREAM,
        command_stream: str = COMMAND_STREAM,
        tracer: Tracer | None = None,
    ):
        self._session = session
        self._event_stream = event_stream
        self._command_stream = command_stream
        self._tracer = tracer

    async def publish(self, event: MessageEnvelope) -> None:
        if event.message_kind != "event":
            raise ValueError("EventBus accepts event messages only")
        await self._enqueue(event, self._event_stream)

    async def send(self, command: MessageEnvelope) -> None:
        if command.message_kind != "command":
            raise ValueError("CommandBus accepts command messages only")
        await self._enqueue(command, self._command_stream)

    async def _enqueue(self, message: MessageEnvelope, stream: str) -> None:
        metadata: dict[str, str] = {}
        if self._tracer is not None:
            with self._tracer.start_as_current_span(
                "messaging.outbox.create",
                attributes={
                    "messaging.system": "redis",
                    "messaging.destination.name": stream,
                },
            ):
                inject_trace_context(metadata)
                await self._add(message, stream, metadata)
            return
        await self._add(message, stream, metadata)

    async def _add(
        self, message: MessageEnvelope, stream: str, metadata: dict[str, str]
    ) -> None:
        self._session.add(
            OutboxMessage(
                job_id=message.message_id,
                stream=stream,
                payload_field="message",
                payload=message.model_dump(mode="json"),
                transport_metadata=metadata,
            )
        )
        await self._session.flush()
