import asyncio
import json

from app.agent_runtime.voice_processing_executor import VoiceProcessingExecutor
from app.agent_runtime.voice_session import VoiceSession
from app.agent_runtime.voice_ws import _handle_message
from app.core.config import AgentRuntimeSettings
from app.core.context import VoiceRuntimeContext
from app.voice.stt.streaming import ElevenLabsStreamingSTTProvider, StreamingTranscriptEvent


class FakeSocket:
    def __init__(self, incoming):
        self.incoming = list(incoming)
        self.sent = []
        self.closed = False

    async def recv(self):
        return self.incoming.pop(0)

    async def send(self, value):
        self.sent.append(json.loads(value))

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.incoming:
            await asyncio.Future()
        return self.incoming.pop(0)

    async def close(self):
        self.closed = True


def test_elevenlabs_streaming_session_normalizes_events_and_commits():
    socket = FakeSocket([
        json.dumps({"message_type": "session_started"}),
        json.dumps({"message_type": "partial_transcript", "text": "hel"}),
        json.dumps({"message_type": "committed_transcript", "text": "duplicate"}),
        json.dumps({"message_type": "committed_transcript_with_timestamps", "text": "hello", "language_code": "en", "words": []}),
    ])
    calls = []

    async def connect(url, **kwargs):
        calls.append((url, kwargs))
        return socket

    async def run():
        partials = []
        async def on_event(event):
            partials.append(event)
        provider = ElevenLabsStreamingSTTProvider(api_key="secret", websocket_connect=connect)
        session = await provider.open_session(
            model="scribe_v2_realtime", language="en", keyterms=["Codex"],
            on_event=on_event, timeout_seconds=1,
        )
        await session.send_audio(b"pcm")
        final = await asyncio.wait_for(session.finalize(), 1)
        await session.close()
        return partials, final

    partials, final = asyncio.run(run())
    assert partials == [
        StreamingTranscriptEvent(text="hel", is_final=False),
        StreamingTranscriptEvent(text="duplicate", is_final=False, event_type="speech_ended"),
    ]
    assert final.text == "hello"
    assert "secret" not in calls[0][0]
    assert calls[0][1]["additional_headers"] == {"xi-api-key": "secret"}
    assert socket.sent[0]["commit"] is False
    assert socket.sent[1]["commit"] is True
    assert socket.closed


def test_elevenlabs_vad_query_uses_exact_tuning():
    socket = FakeSocket([json.dumps({"message_type": "session_started"})])
    calls = []
    async def connect(url, **kwargs):
        calls.append(url); return socket
    async def run():
        provider = ElevenLabsStreamingSTTProvider(api_key="secret", websocket_connect=connect)
        session = await provider.open_session(
            model="scribe_v2_realtime", language=None, keyterms=[], on_event=lambda event: None,
            timeout_seconds=1, commit_strategy="vad", vad_silence_threshold_seconds=1.5,
            vad_threshold=.4, min_speech_duration_ms=100, min_silence_duration_ms=100,
        )
        await session.close()
    asyncio.run(run())
    assert "commit_strategy=vad" in calls[0]
    assert "vad_silence_threshold_secs=1.5" in calls[0]
    assert "vad_threshold=0.4" in calls[0]
    assert "min_speech_duration_ms=100" in calls[0]
    assert "min_silence_duration_ms=100" in calls[0]


class FakeProviderSession:
    def __init__(self):
        self.audio = []
        self.closed = False

    async def send_audio(self, data):
        self.audio.append(data)

    async def finalize(self):
        return StreamingTranscriptEvent(text="hello", is_final=True, language="en")

    async def wait_for_final(self):
        return StreamingTranscriptEvent(text="hello", is_final=True, event_type="final", language="en")

    async def close(self):
        self.closed = True


class FakeProvider:
    provider_name = "elevenlabs"

    def __init__(self):
        self.session = FakeProviderSession()
        self.on_event = None

    async def open_session(self, **kwargs):
        self.on_event = kwargs["on_event"]
        return self.session


class FakeTranscriptProcessor:
    def __init__(self):
        self.requests = []

    def process_transcript(self, request):
        from tests.test_voice_ws_route import FakeTurnProcessor
        self.requests.append(request)
        return FakeTurnProcessor().process(type("Request", (), {
            "tenant_id": request.tenant_id, "conversation_id": request.conversation_id,
            "channel": request.channel,
        })())


def test_streaming_turn_requires_start_isolated_commit_and_single_processing():
    session = VoiceSession(
        tenant_id="tenant-1", stt_mode="streaming",
        runtime_context=VoiceRuntimeContext(tenant_id="tenant-1", language="en", timezone="UTC"),
    )
    settings = AgentRuntimeSettings(
        public_ws_url="ws://localhost", session_token_secret="x" * 32, stt_mode="streaming"
    )
    provider = FakeProvider()
    processor = FakeTranscriptProcessor()
    executor = VoiceProcessingExecutor(turn_processor=processor, poll_interval_seconds=.001)

    async def run():
        early = await _handle_message(session, {"bytes": b"early"}, settings=settings)
        started = await _handle_message(
            session, {"text": json.dumps({"type": "input_audio_start", "content_type": "audio/pcm", "sample_rate": 16000, "channels": 1})},
            streaming_provider=provider, settings=settings,
        )
        await provider.on_event(StreamingTranscriptEvent(text="hel", is_final=False))
        chunk = await _handle_message(session, {"bytes": b"pcm"}, settings=settings)
        turn_id = started[0]["turn_id"]
        committed = await _handle_message(
            session, {"text": json.dumps({"type": "input_audio_commit", "turn_id": turn_id})},
            voice_processing_executor=executor, settings=settings,
        )
        return early, started, chunk, committed

    try:
        early, started, chunk, committed = asyncio.run(run())
    finally:
        executor.shutdown()
    assert early[0]["type"] == "error"
    assert started[0]["type"] == "input_audio_started"
    assert chunk[0]["turn_id"] == started[0]["turn_id"]
    assert [event["type"] for event in committed] == [
        "transcript_completed", "processing_started", "assistant_response", "assistant_audio", "turn_completed"
    ]
    assert len(processor.requests) == 1
    assert provider.session.closed


def test_call_turn_vad_finalizes_once_and_rejects_manual_commit():
    session = VoiceSession(
        tenant_id="tenant-1", stt_mode="streaming", mode="call",
        runtime_context=VoiceRuntimeContext(tenant_id="tenant-1", language="en", timezone="UTC"),
    )
    settings = AgentRuntimeSettings(
        public_ws_url="ws://localhost", session_token_secret="x" * 32, stt_mode="streaming", call_mode_enabled=True,
    )
    provider, processor = FakeProvider(), FakeTranscriptProcessor()
    executor = VoiceProcessingExecutor(turn_processor=processor, poll_interval_seconds=.001)
    events = []
    async def send(event): events.append(event)
    async def run():
        started = await _handle_message(
            session, {"text": json.dumps({"type": "input_audio_start", "mode": "call", "commit_strategy": "vad",
                                           "content_type": "audio/pcm", "sample_rate": 16000, "channels": 1})},
            streaming_provider=provider, settings=settings, send_event=send, voice_processing_executor=executor,
        )
        rejected = await _handle_message(
            session, {"text": json.dumps({"type": "input_audio_commit", "turn_id": started[0]["turn_id"]})},
            settings=settings,
        )
        await provider.on_event(StreamingTranscriptEvent(text="hello", is_final=False))
        await provider.on_event(StreamingTranscriptEvent(text="hello", is_final=False, event_type="speech_ended"))
        await asyncio.sleep(.05)
        return started, rejected
    try:
        started, rejected = asyncio.run(run())
    finally:
        executor.shutdown()
    assert started[0]["type"] == "listening_started"
    assert rejected[0]["code"] == "invalid_commit_strategy"
    assert [event["type"] for event in events].count("processing_started") == 1
    assert len(processor.requests) == 1
