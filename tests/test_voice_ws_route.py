import base64
import asyncio
import time
from datetime import datetime

from app.agent_runtime.voice_processing_executor import VoiceProcessingExecutor
from app.agent_runtime.voice_session import VoiceSession
from app.api.routes.voice_ws import _handle_message
from app.core.context import VoiceRuntimeContext
from app.schemas.messages import MessageResponse
from app.voice.errors import VoiceValidationError
from app.voice.schemas import SynthesizedAudioResult, TranscriptResult, VoiceMessageResponse


def build_session() -> VoiceSession:
    return VoiceSession(
        tenant_id="tenant-1",
        runtime_context=VoiceRuntimeContext(
            tenant_id="tenant-1",
            language="sk",
            timezone="Europe/Bratislava",
        ),
    )


class FakeTurnProcessor:
    def __init__(self, *, fail: bool = False, delay_seconds: float = 0):
        self.fail = fail
        self.delay_seconds = delay_seconds
        self.requests = []

    def process(self, request):
        self.requests.append(request)
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        if self.fail:
            raise VoiceValidationError("fake processing failed")

        now = datetime.now()
        return VoiceMessageResponse(
            conversation_id=request.conversation_id or "conversation-processed",
            transcript="transcribed text",
            response_text="assistant text",
            audio_url="/api/v1/voice/audio/assistant.mp3",
            transcript_result=TranscriptResult(
                provider="fake_stt",
                text="transcribed text",
                language="sk",
                audio_duration_ms=100,
            ),
            audio=SynthesizedAudioResult(
                provider="fake_tts",
                content_type="audio/mpeg",
                size_bytes=12,
                audio_url="/api/v1/voice/audio/assistant.mp3",
            ),
            agent_trace={},
            metadata={
                "timings": {"total_seconds": 0.1},
                "user_message": MessageResponse(
                    id="user-message-1",
                    tenant_id=request.tenant_id,
                    conversation_id=request.conversation_id,
                    channel=request.channel,
                    role="user",
                    content="transcribed text",
                    status="processed",
                    created_at=now,
                ).model_dump(mode="json"),
            },
        )


def build_executor(processor: FakeTurnProcessor, *, timeout_seconds: float = 1) -> VoiceProcessingExecutor:
    return VoiceProcessingExecutor(
        max_workers=4,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=0.001,
        turn_processor=processor,
    )


def test_voice_ws_handler_accepts_json_events_binary_and_base64_audio():
    session = build_session()

    ping = asyncio.run(_handle_message(session, {"text": '{"type":"ping"}'}))
    binary = asyncio.run(_handle_message(session, {"bytes": b"audio"}))
    base64_audio = asyncio.run(
        _handle_message(
            session,
            {
                "text": (
                    '{"type":"audio_chunk","audio_base64":"'
                    + base64.b64encode(b"more-audio").decode("ascii")
                    + '"}'
                )
            },
        )
    )

    assert ping[0]["type"] == "pong"
    assert binary[0]["type"] == "audio_chunk_received"
    assert binary[0]["source"] == "binary"
    assert binary[0]["size_bytes"] == 5
    assert base64_audio[0]["type"] == "audio_chunk_received"
    assert base64_audio[0]["source"] == "base64"
    assert base64_audio[0]["size_bytes"] == 10
    assert session.audio_chunk_count == 2
    assert session.audio_bytes_received == 15
    assert session.pending_audio_bytes == 15


def test_voice_ws_handler_returns_structured_errors_for_bad_payloads():
    session = build_session()

    invalid_json = asyncio.run(_handle_message(session, {"text": "{broken"}))
    invalid_shape = asyncio.run(_handle_message(session, {"text": '["not-object"]'}))
    invalid_base64 = asyncio.run(
        _handle_message(session, {"text": '{"type":"audio_chunk","audio_base64":"not valid"}'})
    )

    assert invalid_json[0]["type"] == "error"
    assert invalid_json[0]["message"] == "Text messages must be valid JSON"
    assert invalid_shape[0]["type"] == "error"
    assert invalid_shape[0]["message"] == "Text messages must be JSON objects"
    assert invalid_base64[0]["type"] == "error"
    assert invalid_base64[0]["message"] == "audio_base64 must be valid base64"


def test_voice_ws_handler_closes_session_on_session_end_event():
    session = build_session()

    event = asyncio.run(_handle_message(session, {"text": '{"type":"session_end"}'}))

    assert event[0]["type"] == "session_ended"
    assert event[0]["reason"] == "client_requested"
    assert session.closed is True


def test_voice_ws_commit_processes_buffered_audio_and_clears_buffer():
    session = build_session()
    processor = FakeTurnProcessor()
    executor = build_executor(processor)
    session.handle_audio_chunk(b"one-", source="binary")
    session.handle_audio_chunk(b"two", source="binary")

    try:
        events = asyncio.run(
            _handle_message(
                session,
                {
                    "text": (
                        '{"type":"input_audio_commit","content_type":"audio/wav",'
                        '"filename":"turn.wav","metadata":{"commit_id":"commit-1"}}'
                    )
                },
                voice_processing_executor=executor,
            )
        )
    finally:
        executor.shutdown()
    request = processor.requests[0]

    assert [event["type"] for event in events] == [
        "processing_started",
        "transcript_completed",
        "assistant_response",
        "assistant_audio",
        "turn_completed",
    ]
    assert request.audio.data == b"one-two"
    assert request.audio.content_type == "audio/wav"
    assert request.audio.filename == "turn.wav"
    assert request.metadata["commit_id"] == "commit-1"
    assert request.metadata["call_session_id"] == session.call_session_id
    assert events[1]["transcript"] == "transcribed text"
    assert events[2]["text"] == "assistant text"
    assert events[3]["audio_url"] == "/api/v1/voice/audio/assistant.mp3"
    assert events[-1]["conversation_id"] == "conversation-processed"
    assert session.conversation_id == "conversation-processed"
    assert session.pending_chunk_count == 0
    assert session.pending_audio_bytes == 0


def test_voice_ws_commit_failure_keeps_buffer_for_retry():
    session = build_session()
    processor = FakeTurnProcessor(fail=True)
    executor = build_executor(processor)
    session.handle_audio_chunk(b"retry-me", source="binary")

    try:
        events = asyncio.run(
            _handle_message(
                session,
                {"text": '{"type":"input_audio_commit"}'},
                voice_processing_executor=executor,
            )
        )
    finally:
        executor.shutdown()

    assert [event["type"] for event in events] == ["processing_started", "error"]
    assert events[-1]["message"] == "fake processing failed"
    assert session.pending_audio_bytes == 8
    assert session.processing is False


def test_voice_ws_sessions_commit_isolated_buffers():
    first = build_session()
    second = build_session()
    first_processor = FakeTurnProcessor()
    second_processor = FakeTurnProcessor()
    first_executor = build_executor(first_processor)
    second_executor = build_executor(second_processor)
    first.handle_audio_chunk(b"first", source="binary")
    second.handle_audio_chunk(b"second", source="binary")

    try:
        asyncio.run(
            _handle_message(
                first,
                {"text": '{"type":"input_audio_commit"}'},
                voice_processing_executor=first_executor,
            )
        )
        asyncio.run(
            _handle_message(
                second,
                {"text": '{"type":"input_audio_commit"}'},
                voice_processing_executor=second_executor,
            )
        )
    finally:
        first_executor.shutdown()
        second_executor.shutdown()

    assert first_processor.requests[0].audio.data == b"first"
    assert second_processor.requests[0].audio.data == b"second"
    assert first.call_session_id != second.call_session_id


def test_voice_ws_commits_two_sessions_concurrently():
    first = build_session()
    second = build_session()
    processor = FakeTurnProcessor(delay_seconds=0.15)
    executor = build_executor(processor)
    first.handle_audio_chunk(b"first", source="binary")
    second.handle_audio_chunk(b"second", source="binary")

    async def run_commits():
        started = time.perf_counter()
        first_events, second_events = await asyncio.gather(
            _handle_message(
                first,
                {"text": '{"type":"input_audio_commit"}'},
                voice_processing_executor=executor,
            ),
            _handle_message(
                second,
                {"text": '{"type":"input_audio_commit"}'},
                voice_processing_executor=executor,
            ),
        )
        return first_events, second_events, time.perf_counter() - started

    try:
        first_events, second_events, elapsed = asyncio.run(run_commits())
    finally:
        executor.shutdown()

    assert elapsed < 0.25
    assert first_events[-1]["type"] == "turn_completed"
    assert second_events[-1]["type"] == "turn_completed"
    assert {request.audio.data for request in processor.requests} == {b"first", b"second"}


def test_voice_ws_same_session_second_commit_is_rejected_while_processing():
    session = build_session()
    processor = FakeTurnProcessor(delay_seconds=0.15)
    executor = build_executor(processor)
    session.handle_audio_chunk(b"audio", source="binary")
    sent_events = []

    async def send_event(event):
        sent_events.append(event)

    async def run_commit_and_retry():
        first_events = await _handle_message(
            session,
            {"text": '{"type":"input_audio_commit"}'},
            voice_processing_executor=executor,
            send_event=send_event,
        )
        second_events = await _handle_message(
            session,
            {"text": '{"type":"input_audio_commit"}'},
            voice_processing_executor=executor,
            send_event=send_event,
        )
        await session.processing_task
        return first_events, second_events

    try:
        first_events, second_events = asyncio.run(run_commit_and_retry())
    finally:
        executor.shutdown()

    assert first_events[0]["type"] == "processing_started"
    assert second_events[0]["type"] == "error"
    assert second_events[0]["code"] == "processing_busy"
    assert sent_events[-1]["type"] == "turn_completed"


def test_voice_ws_ping_remains_responsive_while_processing():
    session = build_session()
    processor = FakeTurnProcessor(delay_seconds=0.15)
    executor = build_executor(processor)
    session.handle_audio_chunk(b"audio", source="binary")
    sent_events = []

    async def send_event(event):
        sent_events.append(event)

    async def run_commit_and_ping():
        commit_events = await _handle_message(
            session,
            {"text": '{"type":"input_audio_commit"}'},
            voice_processing_executor=executor,
            send_event=send_event,
        )
        ping_events = await _handle_message(session, {"text": '{"type":"ping"}'})
        await session.processing_task
        return commit_events, ping_events

    try:
        commit_events, ping_events = asyncio.run(run_commit_and_ping())
    finally:
        executor.shutdown()

    assert commit_events[0]["type"] == "processing_started"
    assert ping_events[0]["type"] == "pong"
    assert sent_events[-1]["type"] == "turn_completed"


def test_voice_ws_timeout_returns_error_and_preserves_buffer():
    session = build_session()
    processor = FakeTurnProcessor(delay_seconds=0.1)
    executor = build_executor(processor, timeout_seconds=0.02)
    session.handle_audio_chunk(b"retry-me", source="binary")

    try:
        events = asyncio.run(
            _handle_message(
                session,
                {"text": '{"type":"input_audio_commit"}'},
                voice_processing_executor=executor,
            )
        )
    finally:
        executor.shutdown()

    assert [event["type"] for event in events] == ["processing_started", "error"]
    assert events[-1]["code"] == "processing_timeout"
    assert session.pending_audio_bytes == 8
    assert session.processing is False


def test_voice_ws_disconnect_cancels_processing_task_without_clearing_buffer():
    session = build_session()
    processor = FakeTurnProcessor(delay_seconds=0.15)
    executor = build_executor(processor)
    session.handle_audio_chunk(b"retry-me", source="binary")
    sent_events = []

    async def send_event(event):
        sent_events.append(event)

    async def run_commit_and_disconnect():
        await _handle_message(
            session,
            {"text": '{"type":"input_audio_commit"}'},
            voice_processing_executor=executor,
            send_event=send_event,
        )
        task = session.processing_task
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        session.close(cancelled=True)

    try:
        asyncio.run(run_commit_and_disconnect())
    finally:
        executor.shutdown()

    assert sent_events == []
    assert session.closed is True
    assert session.cancelled is True
    assert session.pending_audio_bytes == 8
    assert session.processing is False
