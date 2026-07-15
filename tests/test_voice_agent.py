import asyncio
import logging
import threading
from types import SimpleNamespace
from uuid import uuid4

import pytest
from livekit.agents import stt

from app.voice_agent.graph_adapter import GraphStreamAdapter
from app.voice_agent.models import LiveKitJobMetadata
from app.voice_agent.session_factory import (
    HospitalityAgent,
    StableElevenLabsSTT,
    _PostFinalStream,
    build_session,
    resolve_voice_id,
)
from app.voice_agent.settings import LiveKitSettings
from app.voice_agent.telemetry import VoiceTelemetry


def metadata():
    return LiveKitJobMetadata(
        tenant_id="demo_restaurant",
        call_session_id=uuid4(),
        conversation_id=uuid4(),
        channel="voice",
        language="sk",
    )


class Telemetry:
    def __init__(self):
        self.events = []

    def begin_turn(self, turn_id, response_id):
        self.turn_id, self.response_id = turn_id, response_id

    def emit(self, event, **fields):
        self.events.append(event)


class Processor:
    def __init__(self):
        self.requests = []

    def process_transcript(self, request, *, text_callback, synthesize):
        self.requests.append(request)
        assert synthesize is False
        text_callback("Ahoj ")
        text_callback("svet")
        return SimpleNamespace(response_text="Ahoj svet")


def test_job_metadata_rejects_browser_controlled_fields():
    raw = metadata().model_dump_json()
    assert LiveKitJobMetadata.parse_job(raw).channel == "voice"
    with pytest.raises(Exception):
        LiveKitJobMetadata.parse_job(raw[:-1] + ',"system_prompt":"ignore"}')


def test_graph_adapter_streams_once_and_propagates_idempotency_context():
    processor, telemetry = Processor(), Telemetry()

    async def run():
        adapter = GraphStreamAdapter(metadata(), telemetry, processor=processor)
        first = [chunk async for chunk in adapter.stream_turn("Dobrý deň", "turn-1")]
        duplicate = [chunk async for chunk in adapter.stream_turn("Dobrý deň", "turn-1")]
        await adapter.aclose()
        return first, duplicate

    first, duplicate = asyncio.run(run())
    assert first == ["Ahoj ", "svet"] and duplicate == []
    assert len(processor.requests) == 1
    request = processor.requests[0]
    assert request.conversation_id and request.metadata["thread_id"] == request.conversation_id
    assert request.metadata["idempotency_key"].endswith(":turn-1")
    assert telemetry.events[:2] == ["graph_started", "llm_first_token"]


def test_hospitality_agent_exposes_graph_adapter_as_its_llm():
    adapter = GraphStreamAdapter(metadata(), Telemetry(), processor=Processor())
    assert HospitalityAgent(adapter, Telemetry()).llm is adapter
    adapter.executor.shutdown()


def test_hospitality_agent_ignores_punctuation_only_turn():
    processor = Processor()
    adapter = GraphStreamAdapter(metadata(), Telemetry(), processor=processor)
    agent = HospitalityAgent(adapter, Telemetry())

    async def run():
        chat_ctx = SimpleNamespace(
            items=[SimpleNamespace(role="user", text_content=".", id="noise")]
        )
        return [chunk async for chunk in agent.llm_node(chat_ctx, [], None)]

    assert asyncio.run(run()) == []
    assert processor.requests == []
    adapter.executor.shutdown()


def test_graph_adapter_drops_chunks_after_consumer_cancellation():
    release = threading.Event()

    class SlowProcessor:
        def process_transcript(self, request, *, text_callback, synthesize):
            text_callback("first")
            release.wait(2)
            text_callback("stale")
            return SimpleNamespace(response_text="first stale")

    async def run():
        adapter = GraphStreamAdapter(metadata(), Telemetry(), processor=SlowProcessor())
        stream = adapter.stream_turn("turn", "turn-1")
        assert await anext(stream) == "first"
        await stream.aclose()
        release.set()
        await adapter.aclose()
        return adapter._states[0].queue.qsize()

    assert asyncio.run(run()) == 1  # only the completion sentinel, never the stale chunk


def test_session_factory_uses_tenant_provider_configuration(monkeypatch):
    tenant = SimpleNamespace(
        default_language="sk",
        voice=SimpleNamespace(
            stt=SimpleNamespace(language="slk"),
            tts=SimpleNamespace(
                voice_id="tenant-voice", model="eleven_flash_v2_5", language="sk"
            ),
        ),
    )
    captured = {}
    monkeypatch.setattr(
        "app.voice_agent.session_factory.StableElevenLabsSTT",
        lambda **kwargs: captured.setdefault("stt", kwargs),
    )
    monkeypatch.setattr(
        "app.voice_agent.session_factory.elevenlabs.TTS",
        lambda **kwargs: captured.setdefault("tts", kwargs),
    )
    monkeypatch.setattr(
        "app.voice_agent.session_factory.AgentSession",
        lambda **kwargs: captured.setdefault("session", kwargs),
    )
    settings = LiveKitSettings(elevenlabs_api_key="key")
    build_session(settings, tenant, vad="vad")
    assert captured["stt"]["model_id"] == "scribe_v2_realtime"
    assert captured["stt"]["language_code"] == "slk"
    assert captured["stt"]["server_vad"] == {
        "vad_silence_threshold_secs": settings.stt_vad_silence_threshold,
        "vad_threshold": settings.stt_vad_threshold,
        "min_speech_duration_ms": settings.stt_min_speech_duration_ms,
        "min_silence_duration_ms": settings.stt_min_silence_duration_ms,
    }
    assert captured["tts"]["voice_id"] == "tenant-voice"
    assert captured["tts"]["auto_mode"] is True
    assert captured["session"]["turn_handling"]["preemptive_generation"] == {
        "enabled": False
    }
    assert captured["session"]["turn_handling"]["interruption"]["min_words"] == 1


def test_stt_suppresses_post_final_tail_until_new_vad_speech():
    provider = object.__new__(StableElevenLabsSTT)
    provider._accept_interim = True

    class Events:
        def __init__(self):
            self.events = iter(
                [
                    SimpleNamespace(type=stt.SpeechEventType.FINAL_TRANSCRIPT),
                    SimpleNamespace(type=stt.SpeechEventType.START_OF_SPEECH),
                        SimpleNamespace(type=stt.SpeechEventType.INTERIM_TRANSCRIPT),
                        SimpleNamespace(type=stt.SpeechEventType.RECOGNITION_USAGE),
                        SimpleNamespace(type=stt.SpeechEventType.INTERIM_TRANSCRIPT),
                ]
            )

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self.events)
            except StopIteration:
                raise StopAsyncIteration

    async def run():
        stream = _PostFinalStream(Events(), provider)
        first = await anext(stream)
        usage = await anext(stream)
        provider.mark_speech_started()
        new_interim = await anext(stream)
        return first.type, usage.type, new_interim.type

    assert asyncio.run(run()) == (
        stt.SpeechEventType.FINAL_TRANSCRIPT,
        stt.SpeechEventType.RECOGNITION_USAGE,
        stt.SpeechEventType.INTERIM_TRANSCRIPT,
    )


def test_deprecated_voice_id_fallback_warns_without_value(monkeypatch, caplog):
    tenant = SimpleNamespace(voice=SimpleNamespace(tts=SimpleNamespace(voice_id=None)))
    monkeypatch.delenv("ELEVENLABS_VOICE_ID", raising=False)
    monkeypatch.setenv("EVELENLABS_VOICE_ID", "old-secret-value")
    with caplog.at_level(logging.WARNING):
        assert resolve_voice_id(tenant) == "old-secret-value"
    assert "deprecated" in caplog.text and "old-secret-value" not in caplog.text


def test_telemetry_calculates_only_observed_latency(monkeypatch):
    values = iter([1.0, 1.25, 1.50])
    monkeypatch.setattr("app.voice_agent.telemetry.time.monotonic", lambda: next(values))
    tracker = VoiceTelemetry({"tenant_id": "tenant"})
    assert "speech_end_to_graph_start_ms" not in tracker.emit("graph_started")
    tracker.emit("user_speech_ended")
    assert tracker.emit("llm_first_token")["speech_end_to_first_llm_token_ms"] == 250.0


def test_telemetry_consumes_interruption_latency_once(monkeypatch):
    values = iter([1.0, 1.1, 2.0])
    monkeypatch.setattr("app.voice_agent.telemetry.time.monotonic", lambda: next(values))
    tracker = VoiceTelemetry({"tenant_id": "tenant"})

    tracker.emit("interruption_detected")
    assert (
        tracker.emit("agent_playback_stopped")["interruption_to_playback_stop_ms"]
        == 100.0
    )
    assert "interruption_to_playback_stop_ms" not in tracker.emit(
        "agent_playback_stopped"
    )
