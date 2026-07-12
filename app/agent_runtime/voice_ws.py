import asyncio
import json
import logging
import time
from contextlib import suppress
from typing import Any, Awaitable, Callable
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from starlette.websockets import WebSocketState

from app.agent_runtime.voice_processing_executor import (
    VoiceProcessingExecutor,
    VoiceProcessingTimeoutError,
)
from app.agent_runtime.voice_session import ActiveStreamingTurn, VoiceSession, VoiceSessionPayloadError
from app.core.config import AgentRuntimeSettings
from app.core.context import VoiceRuntimeContext
from app.voice.errors import VoiceServiceError
from app.voice.schemas import FinalizedTranscriptRequest, VoiceMessageResponse
from app.voice.session_token import InvalidVoiceSessionToken
from app.voice.stt.streaming import StreamingTranscriptEvent


logger = logging.getLogger(__name__)
router = APIRouter()
DEFAULT_AUDIO_CONTENT_TYPE = "audio/webm"
SendEvent = Callable[[dict[str, Any]], Awaitable[None]]


@router.websocket("/stream")
async def stream_voice(
    websocket: WebSocket,
    audio_content_type: str | None = None,
) -> None:
    default_audio_content_type = _normalize_optional_text(audio_content_type) or DEFAULT_AUDIO_CONTENT_TYPE
    try:
        claims = websocket.app.state.voice_authenticator.authenticate(
            list(websocket.scope.get("subprotocols", []))
        )
    except (AttributeError, InvalidVoiceSessionToken):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid voice session")
        return

    session = VoiceSession(
        tenant_id=claims.tenant_id,
        conversation_id=claims.conversation_id,
        call_session_id=claims.call_session_id,
        runtime_context=VoiceRuntimeContext(
            tenant_id=claims.tenant_id,
            language=claims.language,
            timezone=claims.timezone,
        ),
        stt_mode="streaming" if claims.mode == "call" else websocket.app.state.agent_runtime_settings.stt_mode,
        mode=claims.mode,
    )
    log_context = {
        "tenant_id": session.tenant_id,
        "call_session_id": session.call_session_id,
    }

    await websocket.accept(subprotocol="voice-session")
    logger.info("Voice WebSocket session started", extra=log_context)
    await websocket.send_json(session.session_started_event())
    processing_task: asyncio.Task | None = None
    async def expire_session():
        await asyncio.sleep(max(0, claims.exp - time.time()))
        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Voice session expired")

    expiry_task = asyncio.create_task(expire_session())
    voice_processing_executor = _get_voice_processing_executor(websocket)

    send_lock = asyncio.Lock()

    async def send_event(event: dict[str, Any]) -> None:
        logger.info(
            "Voice WebSocket event",
            extra={
                **log_context,
                "conversation_id": session.conversation_id,
                "event_type": event["type"],
            },
        )
        async with send_lock:
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
                streaming_provider=websocket.app.state.streaming_stt_provider,
                settings=websocket.app.state.agent_runtime_settings,
                stt_config=websocket.app.state.tenant_config_loader.load(session.tenant_id).voice.stt,
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
        expiry_task.cancel()
        if processing_task is not None and not processing_task.done():
            processing_task.cancel()
            with suppress(asyncio.CancelledError):
                await processing_task
        if session.active_turn:
            await session.active_turn.provider_session.close()
            session.active_turn = None
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
    streaming_provider=None,
    settings: AgentRuntimeSettings | None = None,
    stt_config=None,
) -> list[dict[str, Any]]:
    if session.stt_mode == "streaming":
        settings = settings or AgentRuntimeSettings(
            public_ws_url="ws://localhost", session_token_secret="x" * 32, stt_mode="streaming"
        )
        if "bytes" in message and message["bytes"] is not None:
            return await _streaming_audio(session, message["bytes"], settings=settings)

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
        if session.stt_mode == "streaming":
            if session.mode == "call":
                return [session.error_event("input_audio_commit is not allowed for call turns", code="invalid_commit_strategy")]
            return await _commit_streaming_turn(
                session, payload, voice_processing_executor=voice_processing_executor or VoiceProcessingExecutor(),
                settings=settings, send_event=send_event,
            )
        return await _process_input_audio_commit(
            session,
            payload,
            voice_processing_executor=voice_processing_executor or VoiceProcessingExecutor(),
            default_audio_content_type=default_audio_content_type,
            send_event=send_event,
        )

    if event_type == "input_audio_start" and session.stt_mode == "streaming":
        return await _start_streaming_turn(
            session, payload, provider=streaming_provider, settings=settings, send_event=send_event,
            stt_config=stt_config, voice_processing_executor=voice_processing_executor or VoiceProcessingExecutor(),
        )
    if event_type == "input_audio_cancel" and session.stt_mode == "streaming":
        return await _cancel_streaming_turn(session, payload)
    if event_type == "audio_chunk" and session.stt_mode == "streaming":
        try:
            data = json.loads(json.dumps(payload)).get("audio_base64")
            import base64
            return await _streaming_audio(session, base64.b64decode(data, validate=True), settings=settings)
        except Exception:
            return [session.error_event("audio_base64 must be valid base64")]
    if event_type == "audio_chunk" and session.processing:
        return [session.error_event("Voice turn is already processing", code="processing_busy")]

    try:
        return [session.handle_client_event(payload)]
    except VoiceSessionPayloadError as exc:
        return [session.error_event(str(exc))]


async def _start_streaming_turn(session, payload, *, provider, settings, send_event, stt_config=None, voice_processing_executor=None):
    if session.processing or session.active_turn:
        return [session.error_event("Voice turn is already active", code="processing_busy")]
    if payload.get("content_type") != "audio/pcm" or payload.get("sample_rate") != 16000 or payload.get("channels") != 1:
        return [session.error_event("Streaming audio must be mono audio/pcm at 16000 Hz")]
    mode = payload.get("mode", "manual")
    strategy = payload.get("commit_strategy", "manual")
    if mode != session.mode or strategy != ("vad" if mode == "call" else "manual"):
        return [session.error_event("mode or commit_strategy does not match the signed session", code="mode_mismatch")]
    if mode == "call" and not settings.call_mode_enabled:
        return [session.error_event("Voice call mode is disabled", code="call_mode_disabled")]
    configured_language = session.language or (stt_config.language if stt_config else None)
    if payload.get("language") and configured_language and payload["language"] != configured_language:
        return [session.error_event("language must match the authenticated session")]
    language = payload.get("language") or configured_language
    turn_id = str(uuid4())

    async def on_event(event: StreamingTranscriptEvent):
        turn = session.active_turn
        if not turn or turn.turn_id != turn_id or event.is_final:
            return
        if event.event_type == "speech_ended":
            if not turn.committed:
                turn.committed = True
                turn.committed_at = time.monotonic()
                turn.phase = "finalizing_stt"
                if send_event:
                    await send_event(session._event("speech_ended"))
                asyncio.create_task(_finalize_call_turn(
                    session, turn, voice_processing_executor, settings, send_event
                ))
            return
        turn.partial_sequence += 1
        if event.text.strip() and turn.phase == "listening":
            turn.phase = "user_speaking"
            turn.speech_started_at = time.monotonic()
            if send_event:
                await send_event(session._event("speech_started"))
        if send_event:
            await send_event(session._event(
                "transcript_partial", text=event.text, sequence=turn.partial_sequence,
                is_final=False, provider=provider.provider_name, model=settings.realtime_stt_model,
            ))

    try:
        provider_session = await provider.open_session(
            model=settings.realtime_stt_model, language=language,
            keyterms=stt_config.keyterms if stt_config else [],
            on_event=on_event, timeout_seconds=settings.stt_connect_timeout_seconds,
            commit_strategy=strategy,
            vad_silence_threshold_seconds=settings.call_vad_silence_threshold_seconds,
            vad_threshold=settings.call_vad_threshold,
            min_speech_duration_ms=settings.call_min_speech_duration_ms,
            min_silence_duration_ms=settings.call_min_silence_duration_ms,
        )
    except Exception:
        logger.exception("Realtime STT connection failed", extra={"call_session_id": session.call_session_id})
        return [session.error_event("Realtime STT connection failed", code="stt_connection_failed")]
    session.active_turn = ActiveStreamingTurn(turn_id=turn_id, provider_session=provider_session)
    async def expire_turn():
        await asyncio.sleep(settings.stt_max_turn_seconds)
        turn = session.active_turn
        if turn and turn.turn_id == turn_id and not turn.committed:
            await turn.provider_session.close()
            session.active_turn = None
            if send_event:
                event = session.error_event("Voice turn exceeded maximum duration", code="turn_timeout")
                event["turn_id"] = turn_id
                await send_event(event)
    if mode == "manual":
        session.active_turn.timeout_task = asyncio.create_task(expire_turn())
    return [session._event(
        "listening_started" if mode == "call" else "input_audio_started", content_type="audio/pcm", sample_rate=16000, channels=1,
        language=language, provider=provider.provider_name, model=settings.realtime_stt_model,
    )]


async def _streaming_audio(session, data: bytes, *, settings):
    turn = session.active_turn
    if not turn or turn.committed:
        return [session.error_event("input_audio_start is required before audio")]
    if len(data) > settings.stt_max_chunk_bytes:
        return [session.error_event("Audio chunk is too large", code="audio_chunk_too_large")]
    limit_started = turn.speech_started_at
    limit = settings.call_max_utterance_seconds if session.mode == "call" else settings.stt_max_turn_seconds
    if limit_started is not None and time.monotonic() - limit_started > limit:
        await turn.provider_session.close()
        session.active_turn = None
        return [session.error_event("Voice turn exceeded maximum duration", code="turn_timeout")]
    await turn.provider_session.send_audio(data)
    turn.chunk_count += 1
    turn.audio_bytes += len(data)
    session.audio_chunk_count += 1
    session.audio_bytes_received += len(data)
    return [session._event(
        "audio_chunk_received", source="binary", chunk_index=turn.chunk_count,
        size_bytes=len(data), total_audio_bytes=turn.audio_bytes,
    )]


async def _finalize_call_turn(session, turn, executor, settings, send_event):
    try:
        final = await asyncio.wait_for(turn.provider_session.wait_for_final(), settings.stt_finalize_timeout_seconds)
        if session.active_turn is not turn or turn.agent_started:
            return
        await turn.provider_session.close()
        if not final.text.strip():
            session.active_turn = None
            event = session._event("turn_ignored", reason="empty_transcript")
            event["turn_id"] = turn.turn_id
            await send_event(event)
            return
        turn.agent_started = True
        turn.phase = "agent_processing"
        request = FinalizedTranscriptRequest(
            tenant_id=session.tenant_id, conversation_id=session.conversation_id, transcript=final.text,
            provider="elevenlabs", model=settings.realtime_stt_model, language=final.language,
            metadata={"source": "websocket", "call_session_id": session.call_session_id, "turn_id": turn.turn_id},
        )
        await send_event(session._event(
            "transcript_completed", transcript=final.text, text=final.text, is_final=True,
            language=final.language, provider="elevenlabs", model=settings.realtime_stt_model,
            stt_timings={"commit_to_final_ms": int((time.monotonic() - (turn.committed_at or turn.started_at)) * 1000)},
        ))
        session.processing = True
        await send_event(session._event("processing_started"))
        for event in await _run_streaming_turn(session, executor, request):
            await send_event(event)
    except Exception:
        logger.exception("Call STT finalization failed", extra={"call_session_id": session.call_session_id})
        await turn.provider_session.close()
        if session.active_turn is turn:
            session.active_turn = None
        await send_event(session.error_event("Realtime STT finalization failed", code="stt_finalize_failed"))


async def _cancel_streaming_turn(session, payload):
    turn = session.active_turn
    if not turn or payload.get("turn_id") != turn.turn_id or turn.committed:
        return [session.error_event("No matching cancellable turn")]
    turn_id = turn.turn_id
    await turn.provider_session.close()
    if turn.timeout_task:
        turn.timeout_task.cancel()
    event = session._event("input_audio_cancelled", reason="client_requested")
    event["turn_id"] = turn_id
    session.active_turn = None
    return [event]


async def _commit_streaming_turn(session, payload, *, voice_processing_executor, settings, send_event):
    turn = session.active_turn
    if not turn or payload.get("turn_id") != turn.turn_id:
        return [session.error_event("input_audio_commit turn_id does not match active turn")]
    if turn.committed:
        return [session.error_event("Voice turn is already processing", code="processing_busy")]
    turn.committed = True
    if turn.timeout_task:
        turn.timeout_task.cancel()
    try:
        final = await asyncio.wait_for(turn.provider_session.finalize(), settings.stt_finalize_timeout_seconds)
    except Exception:
        await turn.provider_session.close()
        session.active_turn = None
        return [session.error_event("Realtime STT finalization failed", code="stt_finalize_failed")]
    await turn.provider_session.close()
    transcript_event = session._event(
        "transcript_completed", conversation_id=session.conversation_id,
        transcript=final.text, text=final.text, is_final=True, language=final.language,
        provider="elevenlabs", model=settings.realtime_stt_model,
        stt_timings={"time_to_final_transcript_ms": int((time.monotonic() - turn.started_at) * 1000)},
    )
    request = FinalizedTranscriptRequest(
        tenant_id=session.tenant_id, conversation_id=session.conversation_id,
        transcript=final.text, provider="elevenlabs", model=settings.realtime_stt_model,
        language=final.language, metadata={"source": "websocket", "call_session_id": session.call_session_id,
                                           "turn_id": turn.turn_id, **(payload.get("metadata") or {})},
    )
    session.processing = True
    started = session._event("processing_started")
    if send_event is None:
        return [transcript_event, started, *await _run_streaming_turn(session, voice_processing_executor, request)]
    session.processing_task = asyncio.create_task(
        _run_streaming_turn_and_send(session, voice_processing_executor, request, send_event)
    )
    return [transcript_event, started]


async def _run_streaming_turn_and_send(session, executor, request, send_event):
    for event in await _run_streaming_turn(session, executor, request):
        await send_event(event)


async def _run_streaming_turn(session, executor, request):
    try:
        result = await executor.process_transcript(request)
    except Exception:
        logger.exception("Streaming voice turn processing failed", extra={"call_session_id": session.call_session_id})
        session.finish_processing()
        if session.active_turn:
            await session.active_turn.provider_session.close()
            session.active_turn = None
        return [session.error_event("Voice turn processing failed", code="processing_failed")]
    session.conversation_id = result.response.conversation_id
    events = _events_from_voice_response(session, result.response, processing_duration_ms=result.processing_duration_ms)
    events = [event for event in events if event["type"] != "transcript_completed"]
    session.finish_processing()
    session.active_turn = None
    return events


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
