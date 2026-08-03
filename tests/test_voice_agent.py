import asyncio
import inspect
import logging
from types import SimpleNamespace
from uuid import uuid4

import pytest
from livekit.agents import stt

from app.agent.schemas.voice import VoiceTurnConfig
from app.application.livekit_dispatch import resolve_runtime_tools, resolve_voice_id
from app.contracts.livekit import (
    LiveKitJobMetadata,
    RuntimeToolDefinition,
    SessionChatMessage,
)
from app.tenants.loader import TenantConfigLoader
from app.voice_agent.session_factory import (
    GuardedEndCallTool,
    HospitalityAgent,
    StableElevenLabsSTT,
    TurnCommitState,
    VoiceTurnState,
    _PostFinalStream,
    build_human_handoff_tool,
    build_function_tools,
    build_session,
)
from app.voice_agent.settings import LiveKitSettings
from app.voice_agent.telemetry import VoiceTelemetry


def metadata(**changes):
    values = {
        "tenant_id": "demo_restaurant",
        "call_session_id": str(uuid4()),
        "conversation_id": str(uuid4()),
        "channel": "voice",
        "language": "sk",
        "timezone": "Europe/Bratislava",
        "instructions": "Tenant-only instructions",
        "greeting": "Dobrý deň",
        "tools": resolve_runtime_tools(TenantConfigLoader().load("demo_restaurant")),
        "end_call_enabled": False,
        "chat_history": (SessionChatMessage(role="user", content="Earlier"),),
        "stt_language": "slk",
        "tts_voice_id": "tenant-voice",
        "tts_model": "eleven_flash_v2_5",
        "tts_language": "sk",
        "turn_config": VoiceTurnConfig(),
    }
    values.update(changes)
    return LiveKitJobMetadata(**values)


def tools_for(tenant_id, *capabilities):
    return tuple(
        tool
        for tool in resolve_runtime_tools(TenantConfigLoader().load(tenant_id))
        if tool.backend_capability in capabilities
    )


class Telemetry:
    def __init__(self):
        self.events = []

    def begin_turn(self, turn_id, response_id):
        self.turn_id, self.response_id = turn_id, response_id

    def set_turn_kind(self, kind):
        self.kind = kind

    def emit(self, event, **fields):
        self.events.append((event, fields))

    def mark_turn_committed(self):
        self.emit("turn_committed")

    def mark_llm_started(self):
        self.emit("llm_request_started")

    def mark_llm_first_chunk(self, _attempt):
        self.emit("llm_first_chunk")

    def mark_preemptive_reused(self, **_kwargs):
        pass


class Speech:
    def __init__(self, speech_id="speech-1"):
        self.id = speech_id
        self.interrupted = False
        self.callbacks = []

    def add_done_callback(self, callback):
        self.callbacks.append(callback)


class Backend:
    def __init__(self, *, availability_status="available", allocated_room_type="two_bed"):
        self.messages = []
        self.tools = []
        self.events = []
        self.availability_status = availability_status
        self.allocated_room_type = allocated_room_type

    async def persist_message(self, **payload):
        self.messages.append(payload)
        return {"message_id": "message"}

    async def execute_tool(self, **payload):
        self.tools.append(payload)
        self.events.append(f"tool:{payload['capability']}")
        if payload["capability"] == "reservation.check_availability":
            requested = payload["arguments"]["room_type"]
            return {
                "status": "success",
                "message": self.availability_status,
                "result": {
                    "status": self.availability_status,
                    "requested_room_type": requested,
                    "allocated_room_type": (
                        self.allocated_room_type
                        if self.availability_status == "available"
                        else None
                    ),
                },
            }
        return {"status": "success", "message": "submitted"}


def tool_context(speech, call_id, events=None):
    class Session:
        def say(self, _text, **_kwargs):
            class SpeechPlayback:
                def __await__(self):
                    async def wait():
                        if events is not None:
                            events.append(f"announcement:{call_id}")
                    return wait().__await__()

            return SpeechPlayback()

    return SimpleNamespace(
        function_call=SimpleNamespace(call_id=call_id),
        speech_handle=speech,
        session=Session(),
    )


async def invoke_tool(tool, state, speech_id, arguments, events=None):
    speech = Speech(speech_id)
    state.register_speech(speech)
    task = asyncio.create_task(
        tool._func(tool_context(speech, speech_id, events), arguments)
    )
    await asyncio.sleep(0)
    state.commit_turn(f"turn-{speech_id}")
    return await task


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


def test_livekit_settings_keeps_handoff_outside_environment_config():
    settings = LiveKitSettings(
        api_key="key",
        api_secret="x" * 32,
        elevenlabs_api_key="eleven",
        azure_openai_endpoint="https://example.openai.azure.com",
        azure_openai_api_key="azure-key",
        session_token_secret="s" * 32,
    )
    settings.validate_worker()
    assert settings.api_url == "http://livekit:7880"


def test_human_handoff_request_uses_the_current_room_and_stored_trunk():
    from app.voice_agent.server import build_human_handoff_request

    request = build_human_handoff_request(
        "voice-call",
        "+421900111222",
        "ST_outbound",
        "human-handoff-1",
    )
    assert request.room_name == "voice-call"
    assert request.sip_call_to == "+421900111222"
    assert request.sip_trunk_id == "ST_outbound"
    assert request.participant_identity == "human-handoff-1"
    assert request.wait_until_answered is True


def test_human_handoff_tool_runs_only_after_the_turn_is_committed():
    state = VoiceTurnState()
    speech = Speech("handoff-speech")
    state.register_speech(speech)
    calls = []

    async def handoff(context):
        calls.append(context)
        return "Human handoff started."

    tool = build_human_handoff_tool(handoff, state)
    context = tool_context(speech, "handoff")

    async def run():
        task = asyncio.create_task(tool._func(context, {}))
        await asyncio.sleep(0)
        assert calls == []
        state.commit_turn("handoff-turn")
        return await task

    assert asyncio.run(run()) == "Human handoff started."
    assert calls == [context]


def test_native_tools_wait_for_exact_committed_speech_and_propagate_correlation():
    backend, state, telemetry = Backend(), VoiceTurnState(), Telemetry()
    speech = Speech()
    state.register_speech(speech)
    tools = build_function_tools(
        metadata(tools=tools_for("penzion_grand", "reservation.check_availability")),
        backend,
        state,
        telemetry,
    )
    assert [tool.info.name for tool in tools] == ["check_room_availability"]
    context = tool_context(speech, "tool-1")
    async def run():
        task = asyncio.create_task(
            tools[0]._func(
                context,
                {
                    "check_in": "2026-08-01",
                    "check_out": "2026-08-03",
                    "room_type": "two_bed",
                    "room_count": 1,
                },
            )
        )
        await asyncio.sleep(0)
        assert backend.tools == []
        state.commit_turn("turn-1")
        return await task

    result = asyncio.run(run())
    assert result["status"] == "success"
    assert backend.tools[0]["turn_id"] == "turn-1"
    assert backend.tools[0]["tool_call_id"] == "tool-1"


def test_non_reservation_tool_runs_after_announcement_without_another_user_turn():
    backend, state, telemetry = Backend(), VoiceTurnState(), Telemetry()
    definition = RuntimeToolDefinition(
        public_name="look_up_policy",
        description="Look up a property policy.",
        announcement="Hneď to overím.",
        parameters={
            "type": "object",
            "properties": {"topic": {"type": "string"}},
            "required": ["topic"],
            "additionalProperties": False,
        },
        backend_capability="property.lookup",
    )
    tool = build_function_tools(
        metadata(tools=(definition,)), backend, state, telemetry
    )[0]

    result = asyncio.run(
        invoke_tool(tool, state, "policy-lookup", {"topic": "parking"}, backend.events)
    )

    assert result["status"] == "success"
    assert backend.events == [
        "announcement:policy-lookup",
        "tool:property.lookup",
    ]


def test_tool_announcement_is_session_say_before_backend_and_not_prompt_text():
    backend, state, telemetry = Backend(), VoiceTurnState(), Telemetry()
    definition = RuntimeToolDefinition(
        public_name="look_up_policy",
        description="Look up a property policy.",
        announcement="Overím to.",
        parameters={
            "type": "object",
            "properties": {"topic": {"type": "string"}},
            "required": ["topic"],
            "additionalProperties": False,
        },
        backend_capability="property.lookup",
    )
    tool = build_function_tools(metadata(tools=(definition,)), backend, state, telemetry)[0]

    asyncio.run(invoke_tool(tool, state, "policy-order", {"topic": "parking"}))

    assert [event for event, _ in telemetry.events if event in {
        "tool_call_started",
        "announcement_started",
        "announcement_completed",
        "backend_request_started",
        "tool_call_completed",
    }] == [
        "tool_call_started",
        "announcement_started",
        "announcement_completed",
        "backend_request_started",
        "tool_call_completed",
    ]
    assert "Before calling" not in tool.info.raw_schema["description"]


def test_tool_without_announcement_executes_directly():
    backend, state, telemetry = Backend(), VoiceTurnState(), Telemetry()
    definition = RuntimeToolDefinition(
        public_name="look_up_policy",
        description="Look up a property policy.",
        parameters={
            "type": "object",
            "properties": {"topic": {"type": "string"}},
            "required": ["topic"],
            "additionalProperties": False,
        },
        backend_capability="property.lookup",
    )
    tool = build_function_tools(metadata(tools=(definition,)), backend, state, telemetry)[0]

    asyncio.run(invoke_tool(tool, state, "policy-direct", {"topic": "parking"}))

    events = [event for event, _ in telemetry.events]
    assert events.index("backend_request_started") < events.index("tool_call_completed")
    assert "announcement_started" not in events


def test_backend_failure_uses_normalized_result_and_failure_telemetry():
    class FailingBackend(Backend):
        async def execute_tool(self, **_payload):
            raise RuntimeError("backend unavailable")

    backend, state, telemetry = FailingBackend(), VoiceTurnState(), Telemetry()
    definition = RuntimeToolDefinition(
        public_name="look_up_policy",
        description="Look up a property policy.",
        announcement="Overím to.",
        parameters={
            "type": "object",
            "properties": {"topic": {"type": "string"}},
            "required": ["topic"],
            "additionalProperties": False,
        },
        backend_capability="property.lookup",
    )
    tool = build_function_tools(metadata(tools=(definition,)), backend, state, telemetry)[0]

    result = asyncio.run(invoke_tool(tool, state, "policy-failure", {"topic": "parking"}))

    assert result == {"status": "failed", "error": "backend unavailable"}
    assert "tool_call_failed" in [event for event, _ in telemetry.events]


def test_generic_voice_runtime_has_no_tenant_reservation_fsm():
    from app.voice_agent import session_factory

    source = inspect.getsource(session_factory)
    assert "penzion_grand" not in source
    assert "ReservationStage" not in source
    assert "collecting_guest_details" not in source


@pytest.mark.parametrize(
    ("use_inbound", "manual_phone", "expected_phone"),
    [
        (True, None, "+421900111222"),
        (False, "+421900333444", "+421900333444"),
    ],
)
def test_reservation_phone_respects_inbound_caller_consent(
    use_inbound, manual_phone, expected_phone
):
    backend, state, telemetry = Backend(), VoiceTurnState(), Telemetry()
    speech = Speech()
    state.register_speech(speech)
    tool = build_function_tools(
        metadata(
            tenant_id="penzion_grand",
            tools=tools_for("penzion_grand", "reservation.create_request"),
        ),
        backend,
        state,
        telemetry,
        "+421900111222",
    )[0]
    context = tool_context(speech, "tool-phone")

    async def run():
        task = asyncio.create_task(
            tool._func(
                context,
                {
                    "check_in": "2026-08-29",
                    "check_out": "2026-08-31",
                    "reservation_name": "Ján Novák",
                    "reservation_phone": manual_phone,
                    "use_inbound_caller_number": use_inbound,
                    "room_type": "two_bed",
                    "room_count": 1,
                    "confirmed": True,
                },
            )
        )
        await asyncio.sleep(0)
        state.commit_turn("turn-phone")
        await task

    asyncio.run(run())
    assert tool.info.name == "submit_new_reservation_request"
    assert backend.tools[0]["arguments"]["caller_number"] == "+421900111222"
    assert backend.tools[0]["arguments"]["reservation_phone"] == expected_phone


def test_missing_inbound_number_requires_manual_phone():
    backend, state, telemetry = Backend(), VoiceTurnState(), Telemetry()
    speech = Speech()
    state.register_speech(speech)
    tool = build_function_tools(
        metadata(
            tenant_id="penzion_grand",
            tools=tools_for("penzion_grand", "reservation.create_request"),
        ),
        backend,
        state,
        telemetry,
    )[0]

    async def run():
        task = asyncio.create_task(
            tool._func(
                tool_context(speech, "missing-phone"),
                {
                    "check_in": "2026-08-29",
                    "check_out": "2026-08-31",
                    "reservation_name": "Ján Novák",
                    "reservation_phone": None,
                    "use_inbound_caller_number": True,
                    "room_type": "two_bed",
                    "room_count": 1,
                    "confirmed": True,
                },
            )
        )
        await asyncio.sleep(0)
        state.commit_turn("turn-missing-phone")
        return await task

    result = asyncio.run(run())
    assert result["error"] == "inbound_caller_number_unavailable"
    assert backend.tools == []


def test_announced_tools_continue_in_the_same_turn_for_arbitrary_capabilities():
    backend = Backend()
    state, telemetry = VoiceTurnState(), Telemetry()
    tools = build_function_tools(
        metadata(
            tenant_id="penzion_grand",
            tools=tools_for(
                "penzion_grand",
                "reservation.check_availability",
                "reservation.create_request",
            ),
        ),
        backend,
        state,
        telemetry,
        "+421900111222",
    )
    availability_tool, reservation_tool = tools

    async def invoke(tool, speech_id, call_id, arguments):
        speech = Speech(speech_id)
        state.register_speech(speech)
        task = asyncio.create_task(
            tool._func(tool_context(speech, call_id, backend.events), arguments)
        )
        await asyncio.sleep(0)
        state.commit_turn(f"turn-{call_id}")
        return await task

    async def run():
        await invoke(
            availability_tool,
            "availability-speech",
            "availability",
            {
                "check_in": "2026-08-29",
                "check_out": "2026-08-30",
                "room_type": "two_bed",
                "room_count": 1,
            },
        )
        await invoke(
            reservation_tool,
            "reservation-speech",
            "reservation",
            {
                "check_in": "2026-08-29",
                "check_out": "2026-08-30",
                "reservation_name": "Ján Novák",
                "reservation_phone": None,
                "use_inbound_caller_number": True,
                "room_type": "two_bed",
                "room_count": 1,
                "confirmed": True,
            },
        )

    asyncio.run(run())
    assert backend.events == [
        "announcement:availability",
        "tool:reservation.check_availability",
        "announcement:reservation",
        "tool:reservation.create_request",
    ]
    assert backend.tools[1]["arguments"]["room_type"] == "two_bed"


def test_generic_runtime_does_not_encode_reservation_availability_policy():
    backend = Backend()
    state, telemetry = VoiceTurnState(), Telemetry()
    reservation_tool = build_function_tools(
        metadata(
            tenant_id="penzion_grand",
            tools=tools_for("penzion_grand", "reservation.create_request"),
        ),
        backend,
        state,
        telemetry,
    )[0]

    result = asyncio.run(
        invoke_tool(
            reservation_tool,
            state,
            "reservation",
            {
                "check_in": "2026-08-29",
                "check_out": "2026-08-30",
                "reservation_name": "Ján Novák",
                "reservation_phone": "+421900333444",
                "use_inbound_caller_number": False,
                "room_type": "two_bed",
                "room_count": 1,
                "confirmed": True,
            },
        )
    )
    assert result["status"] == "success"
    assert [call["capability"] for call in backend.tools] == [
        "reservation.create_request"
    ]


def test_caller_number_presence_changes_consent_instruction():
    available = HospitalityAgent(
        metadata(
            tenant_id="penzion_grand",
            tools=tools_for("penzion_grand", "reservation.create_request"),
        ),
        Backend(),
        Telemetry(),
        VoiceTurnState(),
        "+421900111222",
    )
    hidden = HospitalityAgent(
        metadata(
            tenant_id="penzion_grand",
            tools=tools_for("penzion_grand", "reservation.create_request"),
        ),
        Backend(),
        Telemetry(),
        VoiceTurnState(),
    )

    assert "A trusted inbound caller number is available" in available.instructions
    assert "+421900111222" in available.instructions
    assert "No trusted inbound caller number is available" in hidden.instructions


def test_hospitality_agent_persists_only_the_canonical_committed_user_once():
    backend, state, telemetry = Backend(), VoiceTurnState(), Telemetry()
    agent = HospitalityAgent(metadata(tools=()), backend, telemetry, state)
    assert agent.instructions == "Tenant-only instructions"
    message = SimpleNamespace(id="turn-1", raw_text_content="Hello")
    async def run():
        await agent.on_user_turn_completed(None, message)
        assert backend.messages == []
        state.register_speech(Speech())
        agent.accept_user_message(message)
        agent.accept_user_message(message)
        await state.user_persistence[message.id]

    asyncio.run(run())
    assert backend.messages == [{
        "role": "user", "content": "Hello", "turn_id": "turn-1", "item_id": "turn-1"
    }]


def _run_end_call(user_text, *, pending_tools=0):
    state = VoiceTurnState(pending_tool_calls=pending_tools)
    speech = Speech("end-call-speech")
    state.register_speech(speech)
    state.commit_turn("end-call-turn")

    class Session:
        def __init__(self):
            self.history = SimpleNamespace(
                items=[
                    SimpleNamespace(
                        type="message", role="user", raw_text_content=user_text
                    )
                ]
            )
            self.current_agent = SimpleNamespace(
                _get_activity_or_raise=lambda: SimpleNamespace(
                    llm=object(), realtime_llm_session=None
                )
            )
            self.shutdowns = 0
            self.close_callback = None

        def once(self, event, callback):
            if event == "close":
                self.close_callback = callback

        def shutdown(self):
            self.shutdowns += 1

    session = Session()
    toolset = GuardedEndCallTool(state)
    context = SimpleNamespace(
        session=session,
        speech_handle=speech,
        function_call=SimpleNamespace(call_id="end-call"),
    )
    result = asyncio.run(toolset.tools[0]._func(context))
    return result, session, speech, toolset


def test_penzion_agent_registers_official_end_call_tool():
    agent = HospitalityAgent(
        metadata(tenant_id="penzion_grand", tools=(), end_call_enabled=True),
        Backend(),
        Telemetry(),
        VoiceTurnState(),
    )
    toolset = next(tool for tool in agent.tools if isinstance(tool, GuardedEndCallTool))
    assert toolset.tools[0].info.name == "end_call"
    assert "'dobre' or 'okay'" in toolset.tools[0].info.description


def test_explicit_goodbye_ends_only_after_farewell_playout():
    result, session, speech, _toolset = _run_end_call(
        "Ďakujem, to je všetko. Dovidenia."
    )
    assert "active conversation language" in result
    assert session.shutdowns == 0
    assert session.close_callback is not None
    assert _toolset._delete_room is True
    for callback in speech.callbacks:
        callback(speech)
    assert session.shutdowns == 1


def test_ambiguous_acknowledgement_does_not_end_call():
    result, session, _speech, _toolset = _run_end_call("Dobre, ďakujem.")
    assert "did not clearly end" in result
    assert session.shutdowns == 0


def test_pending_capability_prevents_end_call():
    result, session, _speech, _toolset = _run_end_call(
        "Dovidenia.", pending_tools=1
    )
    assert "another tool is still running" in result
    assert session.shutdowns == 0


def test_cancelled_speculative_tool_never_reaches_backend_and_wait_has_no_orphans():
    backend, state, telemetry = Backend(), VoiceTurnState(), Telemetry()
    speech = Speech()
    state.register_speech(speech)
    tool = build_function_tools(
        metadata(tools=tools_for("penzion_grand", "reservation.check_availability")),
        backend,
        state,
        telemetry,
    )[0]
    context = SimpleNamespace(
        function_call=SimpleNamespace(call_id="tool-cancelled"), speech_handle=speech
    )

    async def run():
        task = asyncio.create_task(
            tool._func(
                context,
                {
                    "check_in": "2026-08-01",
                    "check_out": "2026-08-03",
                    "room_type": "two_bed",
                    "room_count": 1,
                },
            )
        )
        await asyncio.sleep(0)
        state.cancel_speech(speech.id)
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0)
        assert not [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]

    asyncio.run(run())
    assert backend.tools == []


def test_turn_commit_states_are_idempotent_and_call_local():
    first, second = TurnCommitState("speech-1"), TurnCommitState("speech-2")
    first.commit("turn-1")
    first.commit("turn-1")
    second.cancel()
    second.cancel()
    assert first.committed.is_set() and not second.committed.is_set()
    assert second.cancelled.is_set() and first.turn_id == "turn-1"


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


def test_preemptive_telemetry_reports_real_head_start_and_reuse(monkeypatch):
    values = iter([0.0, 0.1, 0.2, 0.3, 0.5, 0.6, 1.0, 1.1])
    monkeypatch.setattr("app.voice_agent.telemetry.time.monotonic", lambda: next(values))
    tracker = VoiceTelemetry(
        {"tenant_id": "tenant"},
        configuration=VoiceTurnConfig(preemptive_generation={"enabled": True}),
    )
    tracker.emit("speech_started")
    attempt = tracker.mark_llm_started()
    tracker.mark_llm_first_chunk(attempt)
    tracker.mark_turn_committed()
    tracker.mark_preemptive_reused()
    tracker.begin_turn("turn", "response")
    trace = tracker.emit_trace()
    assert trace["durations_ms"]["preemptive_head_start_ms"] == 700.0
    assert trace["durations_ms"]["first_chunk_before_commit_ms"] == 400.0
    assert trace["flags"]["preemptive_generation_used"] is True
    assert trace["flags"]["preemptive_response_reused"] is True


def test_interruption_keeps_the_interrupted_turn_correlation():
    tracker = VoiceTelemetry({"tenant_id": "tenant"}, configuration=VoiceTurnConfig())
    tracker.begin_turn("turn", "response")
    tracker.agent_state = "speaking"
    tracker.emit("speech_started")
    event = tracker.emit("interruption_detected")
    assert event["turn_id"] == "turn"
    assert event["response_id"] == "response"


def test_worker_disconnect_requests_backend_finalization_once(monkeypatch):
    from app.voice_agent import server as voice_server

    calls = []
    state = VoiceTurnState()

    class Session:
        def __init__(self):
            self.history = SimpleNamespace(items=[])
            self.llm = object()
            self.stt = SimpleNamespace(mark_speech_started=lambda: None)

        def on(self, _event):
            return lambda callback: callback

        async def start(self, **_kwargs):
            pass

        async def aclose(self):
            pass

    class RuntimeBackend:
        instance = None

        def __init__(self, *_args):
            self.finalizations = []
            RuntimeBackend.instance = self

        async def finalize_call(self, **payload):
            self.finalizations.append(payload)
            return {"finalization_status": "pending"}

        async def aclose(self):
            pass

    class RuntimeTelemetry:
        def __init__(self, *_args, **_kwargs):
            pass

        def emit(self, *_args, **_kwargs):
            pass

        def bind_session(self, *_args, **_kwargs):
            pass

        async def aclose(self):
            pass

    class Context:
        def __init__(self, raw_metadata):
            self.job = SimpleNamespace(metadata=raw_metadata.model_dump_json())
            self.room = SimpleNamespace(
                name=f"voice-{raw_metadata.call_session_id}",
                local_participant=SimpleNamespace(),
            )
            self.shutdown = None

        async def connect(self, **_kwargs):
            pass

        async def wait_for_participant(self):
            return SimpleNamespace(
                attributes={"sip.phoneNumber": "+421900111222"}, identity="sip-user"
            )

        def add_shutdown_callback(self, callback):
            self.shutdown = callback

    job = metadata(
        tenant_id="penzion_grand",
        greeting=None,
        tools=(),
    )
    ctx = Context(job)
    session = Session()
    monkeypatch.setattr(voice_server, "build_vad", lambda _config: object())
    monkeypatch.setattr(voice_server, "build_session", lambda *_args: session)
    monkeypatch.setattr(voice_server, "VoiceTurnState", lambda: state)
    monkeypatch.setattr(voice_server, "BackendCoreClient", RuntimeBackend)
    monkeypatch.setattr(voice_server, "VoiceTelemetry", RuntimeTelemetry)
    monkeypatch.setattr(voice_server, "HospitalityAgent", lambda *_args: object())
    monkeypatch.setattr(
        voice_server,
        "LiveKitBackendTokenCodec",
        lambda _secret: SimpleNamespace(encode=lambda _claims: "token"),
    )
    monkeypatch.setattr(
        voice_server,
        "settings",
        SimpleNamespace(
            session_token_secret="secret",
            backend_token_ttl_seconds=60,
            backend_url="http://backend",
        ),
    )

    async def run():
        await voice_server.voice_agent(ctx)
        assert RuntimeBackend.instance.finalizations == []
        state.user_persistence["final-user-turn"] = asyncio.create_task(asyncio.sleep(0))
        await ctx.shutdown("participant disconnected")
        await ctx.shutdown("duplicate callback")

    asyncio.run(run())
    calls = RuntimeBackend.instance.finalizations
    assert len(calls) == 1
    assert calls[0]["call_session_id"] == str(job.call_session_id)
    assert calls[0]["caller_phone"] == "+421900111222"
    assert calls[0]["outcome"] == "completed"
