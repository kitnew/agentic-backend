import base64

from app.agent_runtime.voice_session import VoiceSession
from app.core.context import VoiceRuntimeContext


def build_session() -> VoiceSession:
    return VoiceSession(
        tenant_id="tenant-1",
        conversation_id="conversation-1",
        runtime_context=VoiceRuntimeContext(
            tenant_id="tenant-1",
            language="sk",
            timezone="Europe/Bratislava",
        ),
    )


def test_voice_sessions_have_unique_call_ids_and_isolated_state():
    first = build_session()
    second = build_session()

    first_audio_event = first.handle_audio_chunk(b"one", source="binary")
    second_audio_event = second.handle_audio_chunk(b"two-two", source="binary")
    first.transcript_parts.append("hello")

    assert first.call_session_id != second.call_session_id
    assert first.audio_chunk_count == 1
    assert first.audio_bytes_received == 3
    assert first_audio_event["call_session_id"] == first.call_session_id
    assert second.audio_chunk_count == 1
    assert second.audio_bytes_received == 7
    assert second_audio_event["call_session_id"] == second.call_session_id
    assert second.transcript_parts == []
    assert first.pending_audio_bytes == 3
    assert second.pending_audio_bytes == 7


def test_voice_session_handles_ping_base64_audio_and_close():
    session = build_session()

    started = session.session_started_event()
    pong = session.handle_client_event({"type": "ping"})
    audio = session.handle_client_event(
        {
            "type": "audio_chunk",
            "audio_base64": base64.b64encode(b"audio").decode("ascii"),
        }
    )
    ended = session.session_ended_event(reason="client_requested")

    assert started["type"] == "session_started"
    assert started["language"] == "sk"
    assert started["timezone"] == "Europe/Bratislava"
    assert pong["type"] == "pong"
    assert audio["type"] == "audio_chunk_received"
    assert audio["source"] == "base64"
    assert audio["size_bytes"] == 5
    assert ended["type"] == "session_ended"
    assert ended["audio_chunks_received"] == 1
    assert session.closed is True


def test_voice_session_builds_pipeline_request_from_buffer_and_clears_after_success():
    session = build_session()
    session.handle_audio_chunk(b"first-", source="binary")
    session.handle_audio_chunk(b"second", source="binary")

    request = session.build_voice_message_request(
        content_type="audio/webm",
        filename="turn.webm",
        metadata={"commit_id": "commit-1"},
    )

    assert request.tenant_id == "tenant-1"
    assert request.conversation_id == "conversation-1"
    assert request.channel == "voice"
    assert request.audio.filename == "turn.webm"
    assert request.audio.content_type == "audio/webm"
    assert request.audio.data == b"first-second"
    assert request.audio.size_bytes == 12
    assert request.metadata["source"] == "websocket"
    assert request.metadata["call_session_id"] == session.call_session_id
    assert request.metadata["audio_chunk_count"] == 2
    assert request.metadata["audio_size_bytes"] == 12
    assert request.metadata["commit_id"] == "commit-1"

    session.clear_audio_buffer()

    assert session.pending_chunk_count == 0
    assert session.pending_audio_bytes == 0
