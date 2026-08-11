from uuid import UUID

from contracts import CallEventPayload, MessageEnvelope


def call_event(
    call_id: UUID,
    tenant_id: UUID,
    status: str,
    *,
    failure_reason: str | None = None,
    causation_id: UUID | None = None,
) -> MessageEnvelope:
    event_type = f"call.{status}"
    return MessageEnvelope(
        message_kind="event",
        message_type=event_type,
        correlation_id=call_id,
        causation_id=causation_id,
        tenant_id=tenant_id,
        payload=CallEventPayload(
            call_id=call_id,
            status=status,  # type: ignore[arg-type]
            failure_reason=failure_reason,
        ).model_dump(mode="json"),
    )
