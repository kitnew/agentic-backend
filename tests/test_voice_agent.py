import asyncio
import logging
from types import SimpleNamespace
from uuid import uuid4

import pytest
from livekit.agents import stt

from app.voice.latency import VoiceTurnConfig
from app.voice_agent.models import LiveKitJobMetadata, SessionChatMessage
from app.voice_agent.session_factory import (
    HospitalityAgent,
    StableElevenLabsSTT,
    VoiceTurnState,
    _PostFinalStream,
    build_function_tools,
    build_session,
    resolve_voice_id,
)
from app.voice_agent.settings import LiveKitSettings
from app.voice_agent.telemetry import VoiceTelemetry


def metadata(**changes):
    values = {
        "tenant_id": "demo_restaurant",
        "call_session_id": uuid4(),
        "conversation_id": uuid4(),
        "channel": "voice",
        "language": "sk",
        "timezone": "Europe/Bratislava",
        "instructions": "Tenant-only instructions",
        "greeting": "Dobrý deň",
        "enabled_capabilities": (
            "reservation.check_availability",
            "reservation.create_request",
        ),
        "chat_history": (SessionChatMessage(role="user", content="Earlier"),),
        "stt_language": "slk",
        "tts_voice_id": "tenant-voice",
        "tts_model": "eleven_flash_v2_5",
        "tts_language": "sk",
        "turn_config": VoiceTurnConfig(),
    }
    values.update(changes)
    return LiveKitJobMetadata(**values)


class Telemetry:
    def __init__(self):
        self.events = []

    def begin_turn(self, turn_id, response_id):
        self.turn_id, self.response_id = turn_id, response_id

    def set_turn_kind(self, kind):
        self.kind = kind

    def emit(self, event, **fields):
        self.events.append((event, fields))


class Backend:
    def __init__(self):
        self.messages = []
        self.tools = []

    async def persist_message(self, **payload):
        self.messages.append(payload)
        return {"message_id": "message"}

    async def execute_tool(self, **payload):
        self.tools.append(payload)
        return {"status": "success", "message": "available"}


def test_job_metadata_is_immutable_and_rejects_browser_fields():
    raw = metadata().model_dump_json()
    parsed = LiveKitJobMetadata.parse_job(raw)
    assert parsed.instructions == "Tenant-only instructions"
    with pytest.raises(Exception):
        LiveKitJobMetadata.parse_job(raw[:-1] + ',"system_prompt":"ignore"}')


def test_session_factory_maps_milliseconds_and_stt_fields_to_sdk(monkeypatch):
    captured = {}
    monkeypatch.setattr("app.voice_agent.session_factory.StableElevenLabsSTT", lambda **kwargs: captured.setdefault("stt", kwargs))
    monkeypatch.setattr("app.voice_agent.session_factory.openai.LLM.with_azure", lambda **kwargs: captured.setdefault("llm", kwargs))
    monkeypatch.setattr("app.voice_agent.session_factory.elevenlabs.TTS", lambda **kwargs: captured.setdefault("tts", kwargs))
    monkeypatch.setattr("app.voice_agent.session_factory.AgentSession", lambda **kwargs: captured.setdefault("session", kwargs))
    settings = LiveKitSettings(
        elevenlabs_api_key="key",
        azure_openai_endpoint="https://example.openai.azure.com",
        azure_openai_api_key="azure-key",
    )
    build_session(settings, metadata(), "vad")
    assert captured["stt"]["server_vad"] == {
        "vad_silence_threshold_secs": 0.4,
        "vad_threshold": 0.4,
        "min_speech_duration_ms": 100,
        "min_silence_duration_ms": 100,
    }
    turn = captured["session"]["turn_handling"]
    assert turn["endpointing"] == {"mode": "fixed", "min_delay": 0.7, "max_delay": 2.5}
    assert turn["interruption"]["min_duration"] == 0.2
    assert turn["preemptive_generation"] == {"enabled": False, "preemptive_tts": False}
    assert captured["llm"]["azure_deployment"] == "gpt-4o-mini"


def test_native_tools_are_tenant_scoped_and_propagate_correlation():
    backend, state, telemetry = Backend(), VoiceTurnState(current_turn_id="turn-1"), Telemetry()
    tools = build_function_tools(
        metadata(enabled_capabilities=("reservation.check_availability",)),
        backend,
        state,
        telemetry,
    )
    assert [tool.info.name for tool in tools] == ["check_room_availability"]
    context = SimpleNamespace(function_call=SimpleNamespace(call_id="tool-1"))
    async def run():
        state.user_persistence["turn-1"] = asyncio.get_running_loop().create_future()
        state.user_persistence["turn-1"].set_result({"message_id": "user"})
        return await tools[0]._func(
            context,
            __import__("datetime").date(2026, 8, 1),
            __import__("datetime").date(2026, 8, 3),
            "double",
            1,
        )

    result = asyncio.run(run())
    assert result["status"] == "success"
    assert backend.tools[0]["turn_id"] == "turn-1"
    assert backend.tools[0]["tool_call_id"] == "tool-1"


def test_hospitality_agent_uses_native_llm_and_persists_user_once():
    backend, state, telemetry = Backend(), VoiceTurnState(), Telemetry()
    agent = HospitalityAgent(metadata(enabled_capabilities=()), backend, telemetry, state)
    assert agent.instructions == "Tenant-only instructions"
    message = SimpleNamespace(id="turn-1", raw_text_content="Hello")
    async def run():
        await agent.on_user_turn_completed(None, message)
        agent.accept_user_message(message)
        await state.user_persistence[message.id]

    asyncio.run(run())
    assert backend.messages == [{
        "role": "user", "content": "Hello", "turn_id": "turn-1", "item_id": "turn-1"
    }]


def test_stt_suppresses_post_final_tail_until_new_vad_speech():
    provider = object.__new__(StableElevenLabsSTT)
    provider._accept_interim = True

    class Events:
        def __init__(self):
            self.events = iter([
                SimpleNamespace(type=stt.SpeechEventType.FINAL_TRANSCRIPT),
                SimpleNamespace(type=stt.SpeechEventType.INTERIM_TRANSCRIPT),
                SimpleNamespace(type=stt.SpeechEventType.RECOGNITION_USAGE),
                SimpleNamespace(type=stt.SpeechEventType.INTERIM_TRANSCRIPT),
            ])
        def __aiter__(self): return self
        async def __anext__(self):
            try: return next(self.events)
            except StopIteration: raise StopAsyncIteration

    async def run():
        stream = _PostFinalStream(Events(), provider)
        first = await anext(stream)
        usage = await anext(stream)
        provider.mark_speech_started()
        interim = await anext(stream)
        return first.type, usage.type, interim.type

    assert asyncio.run(run()) == (
        stt.SpeechEventType.FINAL_TRANSCRIPT,
        stt.SpeechEventType.RECOGNITION_USAGE,
        stt.SpeechEventType.INTERIM_TRANSCRIPT,
    )


def test_deprecated_voice_id_fallback_warns_without_leaking_value(monkeypatch, caplog):
    tenant = SimpleNamespace(voice=SimpleNamespace(tts=SimpleNamespace(voice_id=None)))
    monkeypatch.delenv("ELEVENLABS_VOICE_ID", raising=False)
    monkeypatch.setenv("EVELENLABS_VOICE_ID", "old-secret-value")
    with caplog.at_level(logging.WARNING):
        assert resolve_voice_id(tenant) == "old-secret-value"
    assert "deprecated" in caplog.text and "old-secret-value" not in caplog.text


def test_telemetry_uses_native_llm_events(monkeypatch):
    values = iter([1.0, 1.2, 1.4, 1.8, 2.0, 2.3])
    monkeypatch.setattr("app.voice_agent.telemetry.time.monotonic", lambda: next(values))
    tracker = VoiceTelemetry({"tenant_id": "tenant"}, configuration=VoiceTurnConfig())
    tracker.emit("speech_ended")
    tracker.begin_turn("turn", "response")
    tracker.emit("llm_request_started")
    tracker.emit("llm_first_chunk")
    tracker.emit("llm_completed")
    tracker.emit("tool_call_started")
    tracker.emit("tool_call_completed")
    trace = tracker.emit_trace()
    assert trace["durations_ms"]["llm_ttft_ms"] == 200.0
    assert trace["durations_ms"]["llm_total_ms"] == 600.0
    assert trace["durations_ms"]["tool_execution_ms"] == 300.0
    assert trace["flags"]["preemptive_generation_enabled"] is False


def test_interruption_keeps_the_interrupted_turn_correlation():
    tracker = VoiceTelemetry({"tenant_id": "tenant"}, configuration=VoiceTurnConfig())
    tracker.begin_turn("turn", "response")
    tracker.agent_state = "speaking"
    tracker.emit("speech_started")
    event = tracker.emit("interruption_detected")
    assert event["turn_id"] == "turn"
    assert event["response_id"] == "response"
