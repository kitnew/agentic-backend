import asyncio
import logging
from datetime import datetime

from livekit import api
from sqlalchemy.orm import Session

from app.domain.call_sessions.enums import CallFinalizationStatus, CallSessionStatus
from app.domain.messages.enums import MessageRole
from app.infrastructure.repositories.call_session_repository import CallSessionRepository
from app.infrastructure.repositories.message_repository import MessageRepository
from app.integrations.summary import AzureSummaryClient
from app.integrations.livekit_recording import (
    RecordingHandle,
    RecordingSettings,
    recording_path,
    save_base64_file,
    wait_for_recording,
)
from app.integrations.post_call_webhook import (
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


def format_elevenlabs_transcript(messages) -> list[dict[str, str]]:
    entries = []
    for message in messages:
        if message.role not in {MessageRole.USER, MessageRole.ASSISTANT}:
            continue
        if message.role == MessageRole.ASSISTANT and (message.metadata or {}).get("interrupted"):
            continue
        content = " ".join((message.content or "").split())
        if content:
            entries.append(
                {
                    "role": "agent" if message.role == MessageRole.ASSISTANT else "user",
                    "message": content,
                }
            )
    return entries


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
        call_messages = [
            message
            for message in messages
            if (message.metadata or {}).get("call_session_id") == call.id
        ]
        transcript = format_transcript(call_messages)
        elevenlabs_transcript = format_elevenlabs_transcript(call_messages)
        summary = await asyncio.wait_for(
            (summary_client or AzureSummaryClient()).summarize(transcript), timeout=10
        )
        tenant = (tenant_loader or TenantConfigLoader()).load(call.tenant_id)
        webhook_config = tenant.post_call_transcript
        delivery_error = None
        async def deliver_webhook(config, payload):
            if webhook_sender:
                await webhook_sender(config, payload)
            else:
                await send_post_call_webhook(
                    config,
                    payload,
                    idempotency_key=f"post-call:{call.id}:{payload['type']}",
                )

        if webhook_config and webhook_config.webhook_url and not call.post_call_transcription_sent:
            try:
                await deliver_webhook(
                    webhook_config,
                    _transcription_event(call, elevenlabs_transcript, summary),
                )
                call.post_call_transcription_sent = True
                repository.save(call)
            except Exception as exc:
                delivery_error = exc
                logger.exception(
                    "Post-call transcription webhook failed call_session_id=%s "
                    "conversation_id=%s",
                    call.id,
                    call.conversation_id,
                )
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
                    recording = save_base64_file(handle)
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
        if webhook_config and webhook_config.webhook_url:
            if recording is None:
                delivery_error = delivery_error or RuntimeError(
                    "Post-call audio webhook requires a completed recording"
                )
            elif not call.post_call_audio_sent:
                try:
                    await deliver_webhook(
                        webhook_config,
                        _audio_event(call, tenant, recording),
                    )
                    call.post_call_audio_sent = True
                    repository.save(call)
                except Exception as exc:
                    delivery_error = delivery_error or exc
                    logger.exception(
                        "Post-call audio webhook failed call_session_id=%s "
                        "conversation_id=%s egress_id=%s",
                        call.id,
                        call.conversation_id,
                        call.recording_egress_id,
                    )
        if delivery_error:
            raise delivery_error
        call.transcript = transcript
        call.summary = summary
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


def _transcription_event(call, transcript, summary) -> dict:
    return {
        "type": "post_call_transcription",
        "data": {
            "analysis": {"transcript_summary": summary},
            "transcript": transcript,
            "conversation_initiation_client_data": {
                "dynamic_variables": {
                    "system__time": call.started_at.isoformat(),
                }
            },
            "user_id": call.caller_phone,
            "conversation_id": call.conversation_id,
        },
    }


def _audio_event(call, tenant, recording) -> dict:
    agent = getattr(tenant, "agent", None)
    data = {
        "agent_id": getattr(agent, "profile", "hospitality-voice"),
        "agent_name": getattr(agent, "display_name", None)
        or getattr(tenant, "name", "hospitality-voice"),
        "conversation_id": call.conversation_id,
        "user_id": call.caller_phone,
    }
    if tenant.post_call_transcript.recording_delivery_mode == "base64":
        data["full_audio"] = recording["content"]
    else:
        data["recording_url"] = recording["url"]
    return {"type": "post_call_audio", "data": data}
