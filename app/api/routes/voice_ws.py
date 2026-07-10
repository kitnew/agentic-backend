import asyncio
import json
import logging
from contextlib import suppress
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from starlette.websockets import WebSocketState

from app.agent_runtime.voice_processing_executor import (
    VoiceProcessingExecutor,
    VoiceProcessingTimeoutError,
)
from app.agent_runtime.voice_session import VoiceSession, VoiceSessionPayloadError
from app.core.context import build_voice_runtime_context
from app.voice.errors import VoiceServiceError
from app.voice.schemas import VoiceMessageResponse
from app.tenants.loader import TenantConfigInvalidError, TenantConfigLoader, TenantConfigNotFoundError


logger = logging.getLogger(__name__)
router = APIRouter()
DEFAULT_AUDIO_CONTENT_TYPE = "audio/webm"
SendEvent = Callable[[dict[str, Any]], Awaitable[None]]


@router.websocket("/stream")
async def stream_voice(
    websocket: WebSocket,
    tenant_id: str | None = None,
    conversation_id: str | None = None,
    audio_content_type: str | None = None,
) -> None:
    normalized_tenant_id = _normalize_optional_text(tenant_id)
    normalized_conversation_id = _normalize_optional_text(conversation_id)
    default_audio_content_type = _normalize_optional_text(audio_content_type) or DEFAULT_AUDIO_CONTENT_TYPE

    if normalized_tenant_id is None:
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="tenant_id query parameter is required",
        )
        return

    try:
        tenant_context = TenantConfigLoader().load(normalized_tenant_id)
    except TenantConfigNotFoundError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Tenant config not found")
        return
    except TenantConfigInvalidError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Tenant config is invalid")
        return

    if not tenant_context.voice.enabled:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Voice mode is disabled")
        return

    session = VoiceSession(
        tenant_id=normalized_tenant_id,
        conversation_id=normalized_conversation_id,
        runtime_context=build_voice_runtime_context(tenant_context),
    )
    log_context = {
        "tenant_id": session.tenant_id,
        "call_session_id": session.call_session_id,
    }

    await websocket.accept()
    logger.info("Voice WebSocket session started", extra=log_context)
    await websocket.send_json(session.session_started_event())
    processing_task: asyncio.Task | None = None
    voice_processing_executor = _get_voice_processing_executor(websocket)

    async def send_event(event: dict[str, Any]) -> None:
        logger.info(
            "Voice WebSocket event",
            extra={
                **log_context,
                "conversation_id": session.conversation_id,
                "event_type": event["type"],
            },
        )
        await websocket.send_json(event)

    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break

            events = await _handle_message(
                session,
                message,
                voice_processing_executor=voice_processing_executor,
                default_audio_content_type=default_audio_content_type,
                send_event=send_event,
            )
            for event in events:
                await send_event(event)
            if session.processing_task is not None:
                processing_task = session.processing_task

            if any(event["type"] == "session_ended" for event in events):
                await websocket.close()
                break
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Voice WebSocket session failed", extra=log_context)
        session.close(cancelled=True)
        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        return
    finally:
        if processing_task is not None and not processing_task.done():
            processing_task.cancel()
            with suppress(asyncio.CancelledError):
                await processing_task
        if not session.closed:
            session.close()
        logger.info(
            "Voice WebSocket session closed",
            extra={
                **log_context,
                "conversation_id": session.conversation_id,
                "event_type": "session_closed",
            },
        )


async def _handle_message(
    session: VoiceSession,
    message: dict[str, Any],
    *,
    voice_processing_executor: VoiceProcessingExecutor | None = None,
    default_audio_content_type: str = DEFAULT_AUDIO_CONTENT_TYPE,
    send_event: SendEvent | None = None,
) -> list[dict[str, Any]]:
    if "bytes" in message and message["bytes"] is not None:
        if session.processing:
            return [session.error_event("Voice turn is already processing", code="processing_busy")]
        return [session.handle_audio_chunk(message["bytes"], source="binary")]

    if "text" not in message or message["text"] is None:
        return [session.error_event("Unsupported WebSocket message")]

    try:
        payload = json.loads(message["text"])
    except json.JSONDecodeError:
        return [session.error_event("Text messages must be valid JSON")]

    if not isinstance(payload, dict):
        return [session.error_event("Text messages must be JSON objects")]

    event_type = str(payload.get("type") or "")
    if event_type in {"close", "session_end"}:
        return [session.session_ended_event(reason="client_requested")]

    if event_type == "input_audio_commit":
        return await _process_input_audio_commit(
            session,
            payload,
            voice_processing_executor=voice_processing_executor or VoiceProcessingExecutor(),
            default_audio_content_type=default_audio_content_type,
            send_event=send_event,
        )

    if event_type == "audio_chunk" and session.processing:
        return [session.error_event("Voice turn is already processing", code="processing_busy")]

    try:
        return [session.handle_client_event(payload)]
    except VoiceSessionPayloadError as exc:
        return [session.error_event(str(exc))]


async def _process_input_audio_commit(
    session: VoiceSession,
    payload: dict[str, Any],
    *,
    voice_processing_executor: VoiceProcessingExecutor,
    default_audio_content_type: str,
    send_event: SendEvent | None = None,
) -> list[dict[str, Any]]:
    if session.processing:
        return [session.error_event("Voice turn is already processing", code="processing_busy")]

    content_type = _normalize_payload_text(payload.get("content_type"), "content_type")
    filename = _normalize_payload_text(payload.get("filename"), "filename")
    if isinstance(content_type, dict):
        return [session.error_event(content_type["message"])]
    if isinstance(filename, dict):
        return [session.error_event(filename["message"])]
    content_type = content_type or default_audio_content_type
    metadata = payload.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        return [session.error_event("metadata must be a JSON object")]

    try:
        request = session.build_voice_message_request(
            content_type=content_type,
            filename=filename,
            metadata=metadata,
        )
    except VoiceSessionPayloadError as exc:
        return [session.error_event(str(exc))]

    started_event = session.processing_started_event()
    if send_event is None:
        return [
            started_event,
            *await _run_committed_turn(
                session,
                voice_processing_executor=voice_processing_executor,
                request=request,
            ),
        ]

    session.processing_task = asyncio.create_task(
        _run_committed_turn_and_send(
            session,
            voice_processing_executor=voice_processing_executor,
            request=request,
            send_event=send_event,
        )
    )
    return [started_event]


async def _run_committed_turn_and_send(
    session: VoiceSession,
    *,
    voice_processing_executor: VoiceProcessingExecutor,
    request,
    send_event: SendEvent,
) -> None:
    events = await _run_committed_turn(
        session,
        voice_processing_executor=voice_processing_executor,
        request=request,
    )
    if session.closed:
        return
    for event in events:
        try:
            await send_event(event)
        except Exception:
            logger.exception(
                "Voice WebSocket send failed",
                extra={
                    "tenant_id": session.tenant_id,
                    "call_session_id": session.call_session_id,
                    "conversation_id": session.conversation_id,
                    "event_type": event["type"],
                    "outcome": "send_failed",
                },
            )
            session.close(cancelled=True)
            return


async def _run_committed_turn(
    session: VoiceSession,
    *,
    voice_processing_executor: VoiceProcessingExecutor,
    request,
) -> list[dict[str, Any]]:
    try:
        result = await voice_processing_executor.process(request)
    except asyncio.CancelledError:
        session.finish_processing()
        raise
    except VoiceProcessingTimeoutError as exc:
        session.finish_processing()
        logger.warning(
            "Voice WebSocket turn timed out",
            extra={
                "tenant_id": session.tenant_id,
                "call_session_id": session.call_session_id,
                "conversation_id": session.conversation_id,
                "event_type": "input_audio_commit",
                "processing_duration_ms": voice_processing_executor.timeout_seconds * 1000,
                "outcome": "timeout",
            },
        )
        return [session.error_event(str(exc), code="processing_timeout")]
    except VoiceServiceError as exc:
        session.finish_processing()
        logger.warning(
            "Voice WebSocket turn failed",
            extra={
                "tenant_id": session.tenant_id,
                "call_session_id": session.call_session_id,
                "conversation_id": session.conversation_id,
                "event_type": "input_audio_commit",
                "outcome": "voice_service_error",
            },
        )
        return [session.error_event(exc.public_message, code=exc.__class__.__name__)]
    except Exception:
        session.finish_processing()
        logger.exception(
            "Voice WebSocket turn processing failed",
            extra={
                "tenant_id": session.tenant_id,
                "call_session_id": session.call_session_id,
                "conversation_id": session.conversation_id,
                "event_type": "input_audio_commit",
                "outcome": "processing_failed",
            },
        )
        return [session.error_event("Voice turn processing failed", code="processing_failed")]

    if session.closed:
        session.finish_processing()
        return []

    session.conversation_id = result.response.conversation_id
    session.clear_audio_buffer()
    session.finish_processing()
    logger.info(
        "Voice WebSocket turn completed",
        extra={
            "tenant_id": session.tenant_id,
            "call_session_id": session.call_session_id,
            "conversation_id": session.conversation_id,
            "event_type": "turn_completed",
            "processing_duration_ms": result.processing_duration_ms,
            "outcome": "success",
        },
    )
    return _events_from_voice_response(
        session,
        result.response,
        processing_duration_ms=result.processing_duration_ms,
    )


def _events_from_voice_response(
    session: VoiceSession,
    response: VoiceMessageResponse,
    *,
    processing_duration_ms: int,
) -> list[dict[str, Any]]:
    events = [
        session._event(
            "transcript_completed",
            conversation_id=response.conversation_id,
            transcript=response.transcript,
            transcript_result=response.transcript_result.model_dump(),
        ),
        session._event(
            "assistant_response",
            conversation_id=response.conversation_id,
            text=response.response_text,
            status=(response.agent_trace or {}).get("status"),
        ),
    ]

    if response.audio_url or response.audio_base64:
        events.append(
            session._event(
                "assistant_audio",
                conversation_id=response.conversation_id,
                audio_url=response.audio_url,
                audio_base64=response.audio_base64,
                content_type=response.audio.content_type if response.audio else None,
                size_bytes=response.audio.size_bytes if response.audio else None,
            )
        )

    events.append(
        session._event(
            "turn_completed",
            conversation_id=response.conversation_id,
            processing_duration_ms=processing_duration_ms,
            metadata=response.metadata,
        )
    )
    return events


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_payload_text(value: Any, field_name: str) -> str | dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return {"message": f"{field_name} must be a string"}
    return _normalize_optional_text(value)


def _get_voice_processing_executor(websocket: WebSocket) -> VoiceProcessingExecutor:
    executor = getattr(websocket.app.state, "voice_processing_executor", None)
    if executor is None:
        executor = VoiceProcessingExecutor()
        websocket.app.state.voice_processing_executor = executor
    return executor
