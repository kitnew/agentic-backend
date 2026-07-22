import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domain.call_sessions.enums import CallFinalizationStatus, CallSessionStatus
from app.domain.messages.enums import MessageRole
from app.infrastructure.repositories.call_session_repository import CallSessionRepository
from app.infrastructure.repositories.message_repository import MessageRepository
from app.integrations.google_sheets.client import GoogleSheetsClient
from app.integrations.google_sheets.schemas import GoogleSheetsAppendRowRequest
from app.integrations.summary import AzureSummaryClient
from app.tenants.loader import TenantConfigLoader


def format_transcript(messages) -> str:
    lines = []
    for message in messages:
        if message.role not in {MessageRole.USER, MessageRole.ASSISTANT}:
            continue
        if message.role == MessageRole.ASSISTANT and (message.metadata or {}).get("interrupted"):
            continue
        content = " ".join((message.content or "").split())
        if content:
            lines.append(f"{'Hosť' if message.role == MessageRole.USER else 'Agent'}: {content}")
    return "\n".join(lines)


async def finalize_call(
    db: Session,
    call_session_id: str,
    *,
    summary_client=None,
    sheets=None,
    tenant_loader=None,
) -> dict:
    repository = CallSessionRepository(db)
    call = repository.get(call_session_id, for_update=True)
    if call is None:
        raise RuntimeError(f"Call session not found: {call_session_id}")
    if call.finalization_status == CallFinalizationStatus.COMPLETED:
        return _result(call)
    if call.status == CallSessionStatus.ACTIVE:
        raise RuntimeError("Active call session cannot be finalized")

    call.finalization_status = CallFinalizationStatus.PROCESSING
    call.finalization_error = None
    call.updated_at = datetime.now()
    repository.save(call)
    try:
        messages = MessageRepository(db).list_by_conversation_id(call.conversation_id)
        transcript = format_transcript(
            message
            for message in messages
            if (message.metadata or {}).get("call_session_id") == call.id
        )
        summary = await asyncio.wait_for(
            (summary_client or AzureSummaryClient()).summarize(transcript), timeout=10
        )
        tenant = (tenant_loader or TenantConfigLoader()).load(call.tenant_id)
        updated_range = None
        if config := tenant.post_call_transcript:
            if db.bind and db.bind.dialect.name == "postgresql":
                # ponytail: global lock; use per-sheet allocation if transcript throughput grows.
                db.execute(text("SELECT pg_advisory_xact_lock(773144917)"))
            completion_time = call.ended_at or datetime.now(timezone.utc)
            result = (sheets or GoogleSheetsClient()).append_row_once(
                GoogleSheetsAppendRowRequest(
                    spreadsheet_id=config.spreadsheet_id,
                    sheet_name=config.sheet_name,
                    values=[
                        transcript,
                        summary,
                        completion_time.replace(tzinfo=completion_time.tzinfo or timezone.utc)
                        .astimezone(ZoneInfo(tenant.timezone))
                        .strftime("%d.%m.%Y %H:%M:%S"),
                        str(call.caller_phone or ""),
                    ],
                ),
                idempotency_key=call.id,
            )
            updated_range = result.updated_range
        call.transcript = transcript
        call.summary = summary
        call.transcript_sheet_range = updated_range or call.transcript_sheet_range
        call.finalization_status = CallFinalizationStatus.COMPLETED
        call.finalization_error = None
        call.updated_at = datetime.now()
        repository.save(call)
        return _result(call)
    except Exception as exc:
        db.rollback()
        call = repository.get(call_session_id, for_update=True)
        if call is not None:
            call.finalization_status = CallFinalizationStatus.FAILED
            call.finalization_error = str(exc)
            call.updated_at = datetime.now()
            repository.save(call)
        raise


def _result(call) -> dict:
    return {
        "call_session_id": call.id,
        "finalization_status": call.finalization_status.value,
        "transcript_sheet_range": call.transcript_sheet_range,
    }
