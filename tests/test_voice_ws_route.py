import base64
import asyncio
from datetime import datetime

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
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.requests = []

    def process(self, request):
        self.requests.append(request)
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
    session.handle_audio_chunk(b"one-", source="binary")
    session.handle_audio_chunk(b"two", source="binary")

    events = asyncio.run(
        _handle_message(
            session,
            {
                "text": (
                    '{"type":"input_audio_commit","content_type":"audio/wav",'
                    '"filename":"turn.wav","metadata":{"commit_id":"commit-1"}}'
                )
            },
            turn_processor=processor,
        )
    )
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
    session.handle_audio_chunk(b"retry-me", source="binary")

    events = asyncio.run(
        _handle_message(
            session,
            {"text": '{"type":"input_audio_commit"}'},
            turn_processor=processor,
        )
    )

    assert [event["type"] for event in events] == ["processing_started", "error"]
    assert events[-1]["message"] == "fake processing failed"
    assert session.pending_audio_bytes == 8
    assert session.processing is False


def test_voice_ws_sessions_commit_isolated_buffers():
    first = build_session()
    second = build_session()
    first_processor = FakeTurnProcessor()
    second_processor = FakeTurnProcessor()
    first.handle_audio_chunk(b"first", source="binary")
    second.handle_audio_chunk(b"second", source="binary")

    asyncio.run(
        _handle_message(
            first,
            {"text": '{"type":"input_audio_commit"}'},
            turn_processor=first_processor,
        )
    )
    asyncio.run(
        _handle_message(
            second,
            {"text": '{"type":"input_audio_commit"}'},
            turn_processor=second_processor,
        )
    )

    assert first_processor.requests[0].audio.data == b"first"
    assert second_processor.requests[0].audio.data == b"second"
    assert first.call_session_id != second.call_session_id
