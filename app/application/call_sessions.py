from datetime import datetime
from uuid import uuid4

from fastapi import HTTPException

from app.capabilities.schemas import CapabilityCommand
from app.contracts.livekit import FinalizeLiveKitCallRequest, LiveKitBackendClaims
from app.domain.call_sessions.entities import CallSession
from app.domain.call_sessions.enums import CallFinalizationStatus, CallSessionStatus
from app.infrastructure.repositories.call_session_repository import CallSessionRepository


def require_active_call(
    repository: CallSessionRepository, claims: LiveKitBackendClaims
) -> CallSession:
    call = repository.get(claims.call_session_id)
    if (
        call is None
        or call.tenant_id != claims.tenant_id
        or call.conversation_id != claims.conversation_id
    ):
        raise HTTPException(status_code=404, detail="Call session not found")
    if call.status != CallSessionStatus.ACTIVE:
        raise HTTPException(status_code=409, detail="Call session is terminal")
    return call


def prepare_finalization(
    repository: CallSessionRepository,
    claims: LiveKitBackendClaims,
    request: FinalizeLiveKitCallRequest,
) -> tuple[CallSession, CapabilityCommand | None]:
    if request.call_session_id != claims.call_session_id:
        raise HTTPException(status_code=403, detail="Call session claim mismatch")
    call = repository.get(request.call_session_id, for_update=True)
    if (
        call is None
        or call.tenant_id != claims.tenant_id
        or call.conversation_id != claims.conversation_id
    ):
        raise HTTPException(status_code=404, detail="Call session not found")

    now = datetime.now()
    if call.status == CallSessionStatus.ACTIVE:
        call.status = CallSessionStatus(request.outcome)
        call.ended_at = now
        call.terminal_reason = request.reason
        call.terminal_error = request.error
        call.livekit_job_id = request.livekit_job_id or call.livekit_job_id
        call.recording_egress_id = request.recording_egress_id or call.recording_egress_id
        call.caller_phone = request.caller_phone or call.caller_phone
    if call.finalization_status == CallFinalizationStatus.COMPLETED:
        return call, None
    if call.finalization_status == CallFinalizationStatus.PROCESSING:
        return call, None
    if call.finalization_status == CallFinalizationStatus.FAILED:
        call.finalization_command_id = None
        call.finalization_enqueued_at = None
    if call.finalization_command_id is None:
        call.finalization_command_id = str(uuid4())
    call.finalization_status = CallFinalizationStatus.PENDING
    call.finalization_error = None
    call.updated_at = now
    repository.save(call)
    if call.finalization_enqueued_at is not None:
        return call, None
    return call, CapabilityCommand(
        command_id=call.finalization_command_id,
        tenant_id=call.tenant_id,
        conversation_id=call.conversation_id,
        call_session_id=call.id,
        capability="call",
        action="finalize",
        payload={"call_session_id": call.id},
        idempotency_key=f"call-finalization:{call.id}",
        metadata={"internal": True},
    )


def mark_finalization_enqueued(
    repository: CallSessionRepository, call_session_id: str, command_id: str
) -> CallSession:
    call = repository.get(call_session_id, for_update=True)
    if call is None:
        raise HTTPException(status_code=404, detail="Call session not found")
    if call.finalization_command_id == command_id:
        call.finalization_enqueued_at = datetime.now()
        call.updated_at = call.finalization_enqueued_at
        repository.save(call)
    return call


def mark_finalization_enqueue_failed(
    repository: CallSessionRepository, call_session_id: str, command_id: str, error: str
) -> None:
    call = repository.get(call_session_id, for_update=True)
    if call and call.finalization_command_id == command_id:
        call.finalization_status = CallFinalizationStatus.FAILED
        call.finalization_error = error
        call.updated_at = datetime.now()
        repository.save(call)
