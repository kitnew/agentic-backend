import asyncio
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from livekit import api
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domain.call_sessions.enums import CallFinalizationStatus, CallSessionStatus
from app.domain.messages.enums import MessageRole
from app.infrastructure.repositories.call_session_repository import CallSessionRepository
from app.infrastructure.repositories.message_repository import MessageRepository
from app.integrations.google_sheets.client import GoogleSheetsClient
from app.integrations.google_sheets.schemas import GoogleSheetsAppendRowRequest
from app.integrations.summary import AzureSummaryClient
from app.integrations.livekit_recording import (
    RecordingHandle,
    RecordingSettings,
    recording_path,
    save_base64_file,
    wait_for_recording,
)
from app.integrations.post_call_webhook import (
    RECORDING_BASE64_PLACEHOLDER,
    send_post_call_webhook,
)
from app.tenants.loader import TenantConfigLoader


logger = logging.getLogger(__name__)


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
    recording_client=None,
    webhook_sender=None,
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
        recording = None
        recording_client_owned = False
        if call.recording_egress_id:
            recording_settings = RecordingSettings.from_env()
            recording_client_owned = recording_client is None
            recording_client = recording_client or api.LiveKitAPI(
                url=recording_settings.api_url,
                api_key=recording_settings.api_key,
                api_secret=recording_settings.api_secret,
            )
            handle = RecordingHandle(
                egress_id=call.recording_egress_id,
                room_name=call.livekit_room_name,
                path=recording_path(recording_settings.output_dir, call.id),
            )
            try:
                await wait_for_recording(
                    handle,
                    client=recording_client,
                    settings=recording_settings,
                )
                if not handle.path.is_file():
                    raise RuntimeError(f"Recording file not found: {handle.path}")
                delivery_mode = (
                    tenant.post_call_transcript.recording_delivery_mode
                    if tenant.post_call_transcript
                    else "base64"
                )
                if delivery_mode == "base64":
                    recording = {
                        **save_base64_file(handle),
                        "content": RECORDING_BASE64_PLACEHOLDER,
                    }
                else:
                    base_url = tenant.post_call_transcript.recording_public_base_url
                    recording = {
                        "filename": handle.path.name,
                        "content_type": "audio/ogg",
                        "url": f"{base_url.rstrip('/')}/{handle.path.name}",
                    }
            finally:
                if recording_client_owned:
                    await recording_client.aclose()
        if tenant.post_call_transcript and tenant.post_call_transcript.webhook_url:
            if recording is None:
                raise RuntimeError("Post-call webhook requires a completed recording")
            payload = {
                "tenant_id": call.tenant_id,
                "call_session_id": call.id,
                "room_name": call.livekit_room_name,
                "caller_phone": call.caller_phone,
                "outcome": call.status.value,
                "reason": call.terminal_reason,
                "transcript": transcript,
                "summary": summary,
                "recording": recording,
            }
            await (webhook_sender or send_post_call_webhook)(
                tenant.post_call_transcript,
                payload,
            )
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
        logger.exception(
            "Post-call finalization failed call_session_id=%s room_name=%s egress_id=%s",
            call_session_id,
            getattr(call, "livekit_room_name", None),
            getattr(call, "recording_egress_id", None),
        )
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
