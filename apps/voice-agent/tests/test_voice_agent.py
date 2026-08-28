import asyncio
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from contracts import (
    CapabilityInvocationStatus,
    EffectiveVoiceRuntime,
    HumanHandoffResponse,
    InboundSipClaimResponse,
    RuntimeCapabilityDefinition,
    VoiceAgentRuntimeContext,
)
from livekit import agents, rtc
from livekit.agents.beta.tools import EndCallTool
from livekit.plugins import elevenlabs, openai
from pydantic import ValidationError
from voice_agent.backend import BackendClient
from voice_agent.calculator import calculate, calculator_tool
from voice_agent.event_delivery import MESSAGE_NAMESPACE, message_from_event
from voice_agent.main import (
    SessionTerminalizer,
    assemble_instructions,
    build_agent_tools,
    capability_tool,
    close_failure_reason,
    handoff_tool,
    on_request,
    parse_metadata,
    resolve_call_session_id,
    run_job,
)
from voice_agent.providers import (
    azure_endpoint,
    create_agent_session,
    llm_behavior_options,
    provider_languages,
)
from voice_agent.settings import VoiceAgentSettings
from voice_agent.stt_preflight import InterimPreflightSTT


def settings(**overrides: object) -> VoiceAgentSettings:
    values: dict[str, object] = {
        "livekit_url": "ws://livekit:7880",
        "livekit_api_key": "test-key",
        "livekit_api_secret": "test-secret",
        "livekit_agent_name": "hospitality-voice-agent",
        "backend_core_url": "http://backend:8000",
        "internal_api_audience": "backend-core",
        "voice_agent_service_secret": "v" * 32,
        "elevenlabs_api_key": "eleven-key",
        "azure_openai_api_key": "azure-key",
        "azure_openai_endpoint": "https://test.openai.azure.com",
        "azure_openai_deployment": "deployment",
        "azure_openai_api_version": "2025-01-01-preview",
    }
    values.update(overrides)
    return VoiceAgentSettings.model_validate(values)


def runtime_context() -> VoiceAgentRuntimeContext:
    return VoiceAgentRuntimeContext(
        call_session_id=uuid4(),
        voice_runtime_revision_id=uuid4(),
        voice_runtime=runtime_settings(),
        room_name="call_test",
        locale="sk-SK",
        timezone="Europe/Bratislava",
        agent_display_name="Amelia",
        greeting="Dobry den",
        conversation_scope="property_only",
        prompt={
            "system_prompt": "System prompt",
            "profile_prompt": "Profile prompt",
            "tenant_prompt": "Tenant prompt",
            "knowledge_context": "Knowledge",
            "knowledge_base_revision_id": uuid4(),
        },
    )


def runtime_settings(**overrides: object) -> EffectiveVoiceRuntime:
    payload: dict[str, object] = {
        "locale": "sk-SK",
        "llm": {
            "provider": "azure_openai",
            "model": "model-a",
            "temperature": 0,
        },
        "stt": {
            "provider": "elevenlabs",
            "model": "scribe_v2_realtime",
            "interim_preflight": {
                "enabled": False,
                "min_transcript_chars": 20,
                "min_growth_chars": 12,
                "max_generations_per_turn": 2,
            },
            "server_vad": {
                "silence_threshold_seconds": 0.35,
                "activity_threshold": 0.35,
                "min_speech_ms": 100,
                "min_silence_ms": 350,
            },
        },
        "tts": {
            "provider": "elevenlabs",
            "model": "eleven_flash_v2_5",
            "voice_id": "voice-id",
            "min_sentence_chars": 20,
        },
        "local_vad": {
            "min_speech_seconds": 0.05,
            "min_silence_seconds": 0.25,
            "activation_threshold": 0.5,
        },
        "turn": {
            "detection": "stt",
            "min_endpointing_delay_seconds": 0.1,
            "max_endpointing_delay_seconds": 0.7,
        },
    }
    payload.update(overrides)
    return EffectiveVoiceRuntime.model_validate(payload)


def test_llm_behavior_options_follow_runtime_model() -> None:
    reasoning = runtime_settings(
        llm={
            "provider": "azure_openai",
            "model": "gpt-5.6-terra",
            "temperature": None,
            "reasoning_effort": "none",
        }
    )
    assert llm_behavior_options(reasoning) == {"reasoning_effort": "none"}

    classic = runtime_settings(
        llm={
            "provider": "azure_openai",
            "model": "gpt-4o-mini",
            "temperature": 0,
            "reasoning_effort": "none",
        }
    )
    assert llm_behavior_options(classic) == {"temperature": 0}


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "not-json",
        "{}",
        '{"call_session_id":"not-a-uuid"}',
        '{"call_session_id":"00000000-0000-0000-0000-000000000001","extra":1}',
    ],
)
def test_metadata_rejects_empty_malformed_missing_extra_and_invalid_uuid(
    raw: str,
) -> None:
    with pytest.raises((ValueError, ValidationError)):
        parse_metadata(raw)


@pytest.mark.asyncio
async def test_on_request_accepts_valid_metadata_or_sip_bootstrap() -> None:
    class Request:
        def __init__(self, metadata: str) -> None:
            self.job = SimpleNamespace(metadata=metadata)
            self.accepted = False
            self.terminated: bool | None = None

        async def accept(self) -> None:
            self.accepted = True

        async def reject(self, *, terminate: bool) -> None:
            self.terminated = terminate

    rejected = Request("{}")
    await on_request(rejected)  # type: ignore[arg-type]
    assert rejected.terminated is True
    assert not rejected.accepted

    accepted = Request(f'{{"call_session_id":"{uuid4()}"}}')
    await on_request(accepted)  # type: ignore[arg-type]
    assert accepted.accepted
    assert accepted.terminated is None

    sip = Request("")
    await on_request(sip)  # type: ignore[arg-type]
    assert sip.accepted
    assert sip.terminated is None


@pytest.mark.asyncio
async def test_resolve_call_session_id_keeps_metadata_flow_unchanged() -> None:
    call_id = uuid4()

    class Context:
        job = SimpleNamespace(metadata=f'{{"call_session_id":"{call_id}"}}')

        async def wait_for_participant(self, **kwargs):
            raise AssertionError("metadata flow must not wait for SIP")

    assert (
        await resolve_call_session_id(Context(), object(), 1)  # type: ignore[arg-type]
        == call_id
    )


@pytest.mark.asyncio
async def test_resolve_call_session_id_claims_sip_attributes() -> None:
    call_id = uuid4()

    class Backend:
        request = None

        async def claim_inbound_sip(self, request):
            self.request = request
            return InboundSipClaimResponse(call_session_id=call_id, created=True)

    participant = SimpleNamespace(
        kind=rtc.ParticipantKind.PARTICIPANT_KIND_SIP,
        identity="sip-caller",
        attributes={
            "sip.callID": "SCL_test",
            "sip.callIDFull": "telnyx@example.net",
            "sip.phoneNumber": "+421900111222",
            "sip.trunkPhoneNumber": "+421552301410",
            "sip.trunkID": "ST_test",
            "sip.ruleID": "SDR_test",
        },
    )

    class Context:
        job = SimpleNamespace(metadata="")
        room = SimpleNamespace(name="sip-call-test")

        async def wait_for_participant(self, **kwargs):
            assert rtc.ParticipantKind.PARTICIPANT_KIND_SIP in kwargs["kind"]
            return participant

    backend = Backend()
    assert (
        await resolve_call_session_id(Context(), backend, 1)  # type: ignore[arg-type]
        == call_id
    )
    assert backend.request is not None
    assert backend.request.model_dump(mode="json") == {
        "sip_call_id": "SCL_test",
        "sip_call_id_full": "telnyx@example.net",
        "trunk_id": "ST_test",
        "dispatch_rule_id": "SDR_test",
        "caller_number": "+421900111222",
        "called_number": "+421552301410",
        "room_name": "sip-call-test",
        "participant_identity": "sip-caller",
    }


@pytest.mark.asyncio
async def test_resolve_call_session_id_rejects_non_sip_and_missing_attributes() -> None:
    class Context:
        job = SimpleNamespace(metadata="")
        room = SimpleNamespace(name="room")

        def __init__(self, participant) -> None:
            self.participant = participant

        async def wait_for_participant(self, **kwargs):
            return self.participant

    standard = SimpleNamespace(
        kind=rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD,
        identity="browser",
        attributes={},
    )
    with pytest.raises(ValueError, match="no inbound SIP participant"):
        await resolve_call_session_id(
            Context(standard),
            object(),
            1,  # type: ignore[arg-type]
        )

    incomplete = SimpleNamespace(
        kind=rtc.ParticipantKind.PARTICIPANT_KIND_SIP,
        identity="sip-caller",
        attributes={"sip.callID": "SCL_test"},
    )
    with pytest.raises(ValueError, match="sip.phoneNumber"):
        await resolve_call_session_id(
            Context(incomplete),
            object(),
            1,  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_service_jwt_has_one_requested_scope() -> None:
    client = BackendClient(settings())
    try:
        token = client.service_token("call-session:activate")
        claims = jwt.decode(
            token,
            "v" * 32,
            algorithms=["HS256"],
            audience="backend-core",
        )
        assert claims["service"] == "voice-agent"
        assert claims["scopes"] == ["call-session:activate"]
        assert claims["exp"] - claims["iat"] == 60
    finally:
        await client.aclose()


def test_prompt_assembly_uses_only_runtime_material() -> None:
    instructions = assemble_instructions(runtime_context())
    assert "Timezone: Europe/Bratislava" in instructions
    assert "Current local date: " in instructions
    assert "Current local time: " in instructions
    assert "Conversation scope: property_only" in instructions


@pytest.mark.parametrize(
    ("operation", "operands", "expected"),
    [
        ("add", ["0.1", "0.2"], "0.3"),
        ("subtract", ["5", "2.5"], "2.5"),
        ("multiply", ["55", "3"], "165"),
        ("divide", ["1", "4"], "0.25"),
        ("percentage", ["200", "15"], "30"),
    ],
)
def test_calculator_operations_are_exact(
    operation: str, operands: list[str], expected: str
) -> None:
    from contracts import CalculatorRequest

    assert (
        calculate(CalculatorRequest(operation=operation, operands=operands)) == expected
    )


@pytest.mark.parametrize("operand", ["NaN", "Infinity", "1 + 2", ""])
def test_calculator_rejects_invalid_decimal_values(operand: str) -> None:
    from contracts import CalculatorRequest

    with pytest.raises(ValidationError, match="decimal values"):
        CalculatorRequest(operation="add", operands=[operand, "1"])


@pytest.mark.asyncio
async def test_calculator_tool_returns_result_and_structured_failures() -> None:
    recorded: list[dict[str, object]] = []
    tool = calculator_tool(lambda **values: recorded.append(values))
    context = SimpleNamespace()
    assert await tool._func(  # type: ignore[attr-defined]
        context, {"operation": "multiply", "operands": ["55", "3"]}
    ) == {"result": "165"}
    assert await tool._func(  # type: ignore[attr-defined]
        context, {"operation": "divide", "operands": ["1", "0"]}
    ) == {
        "status": "failed",
        "error_code": "division_by_zero",
        "message": "The calculator cannot divide by zero",
    }
    assert await tool._func(  # type: ignore[attr-defined]
        context, {"operation": "add", "operands": ["1 + 2", "3"]}
    ) == {
        "status": "failed",
        "error_code": "invalid_input",
        "message": "Invalid calculator input",
    }
    assert [item["status"] for item in recorded] == ["ok", "failed", "failed"]
    assert all(item["name"] == "calculator.calculate" for item in recorded)


def test_calculator_is_always_added_before_tenant_tools() -> None:
    context = runtime_context()
    tools = build_agent_tools(
        context.model_copy(update={"capabilities": []}), None, uuid4()
    )  # type: ignore[arg-type]
    assert len(tools) == 2
    assert tools[0]._info.name == "calculator"  # type: ignore[attr-defined]
    assert (
        "one arithmetic operation per call" in tools[0]._info.raw_schema["description"]
    )  # type: ignore[attr-defined]
    assert isinstance(tools[1], EndCallTool)
    assert tools[1].id == "end_call"
    assert [tool.info.name for tool in tools[1].tools] == ["end_call"]


@pytest.mark.asyncio
async def test_handoff_tool_is_semantic_and_relinquishes() -> None:
    class Backend:
        def __init__(self) -> None:
            self.requests: list[object] = []

        async def transfer_to_human(self, call_id, request):
            self.requests.append(request)
            return HumanHandoffResponse(destination=request.destination)

    class Session:
        def __init__(self) -> None:
            self.shutdowns: list[bool] = []

        def shutdown(self, *, drain: bool = True) -> None:
            self.shutdowns.append(drain)

    call_id = uuid4()
    backend = Backend()
    handed_off: list[bool] = []
    runtime = VoiceAgentRuntimeContext.model_validate(
        {
            **runtime_context().model_dump(),
            "handoff_destinations": {
                "reception": {"description": "Reservations and reception requests"}
            },
        }
    )
    tools = build_agent_tools(runtime, backend, call_id)  # type: ignore[arg-type]
    assert [tools[0]._info.name, tools[1].id, tools[2]._info.name] == [  # type: ignore[attr-defined]
        "calculator",
        "end_call",
        "transfer_to_human",
    ]
    tool = handoff_tool(  # type: ignore[arg-type]
        runtime, backend, call_id, lambda: handed_off.append(True)
    )
    schema = tool._info.raw_schema  # type: ignore[attr-defined]
    assert schema["parameters"]["properties"]["destination"]["enum"] == ["reception"]
    assert "phone" not in str(schema).lower()
    session = Session()
    result = await tool._func(  # type: ignore[attr-defined]
        SimpleNamespace(
            session=session,
            function_call=SimpleNamespace(call_id="tool-handoff-1"),
        ),
        {"destination": "reception", "reason": "Guest asked for reception"},
    )
    assert result == {"status": "transferred", "destination": "reception"}
    assert handed_off == [True]
    assert session.shutdowns == [True]
    assert backend.requests[0].destination == "reception"  # type: ignore[union-attr]


def test_handoff_tool_is_absent_when_unconfigured() -> None:
    tools = build_agent_tools(runtime_context(), None, uuid4())  # type: ignore[arg-type]
    assert [tools[0]._info.name, tools[1].id] == ["calculator", "end_call"]  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_capability_timeout_returns_only_safe_semantics() -> None:
    class Backend:
        async def invoke_capability(self, call_id, request):
            raise TimeoutError

    class Session:
        async def say(self, text, **kwargs):
            return None

    context = SimpleNamespace(
        session=Session(), function_call=SimpleNamespace(call_id="tool-call")
    )
    definition = RuntimeCapabilityDefinition(
        semantic_key="reservation.submit_request",
        semantic_version=1,
        tool_name="reservation_submit_request",
        description="Submit a reservation request.",
        announcement="I will submit your reservation request now.",
        input_schema={"type": "object"},
    )
    tool = capability_tool(definition, Backend(), uuid4())  # type: ignore[arg-type]
    result = await tool._func(context, {})  # type: ignore[attr-defined,arg-type]
    assert result == {
        "status": "request_submission_pending",
        "error_code": "execution_timeout",
        "message": "The request is still being processed; I could not confirm submission yet",
    }


@pytest.mark.asyncio
async def test_availability_capability_records_success_without_arguments() -> None:
    recorded: list[dict[str, object]] = []

    class Backend:
        async def invoke_capability(self, call_id, request):
            return object()

        async def wait_for_capability(self, call_id, invocation):
            return SimpleNamespace(
                status=CapabilityInvocationStatus.SUCCEEDED,
                semantic_result={"status": "available"},
            )

    class Session:
        async def say(self, text, **kwargs):
            return None

    definition = RuntimeCapabilityDefinition(
        semantic_key="reservation.check_availability",
        semantic_version=1,
        tool_name="reservation_check_availability",
        description="Check availability.",
        announcement="I will check availability.",
        input_schema={"type": "object"},
    )
    tool = capability_tool(  # type: ignore[arg-type]
        definition,
        Backend(),
        uuid4(),
        lambda **values: recorded.append(values),
    )
    result = await tool._func(  # type: ignore[attr-defined]
        SimpleNamespace(
            session=Session(), function_call=SimpleNamespace(call_id="tool-call")
        ),
        {},
    )
    assert result == {"status": "available"}
    assert len(recorded) == 1
    assert recorded[0]["name"] == "reservation.check_availability"
    assert recorded[0]["version"] == "1"
    assert recorded[0]["status"] == "ok"
    assert recorded[0]["error_type"] is None
    assert recorded[0]["duration_seconds"] >= 0


@pytest.mark.asyncio
async def test_capability_with_empty_success_result_returns_submitted() -> None:
    recorded: list[dict[str, object]] = []

    class Backend:
        async def invoke_capability(self, call_id, request):
            return object()

        async def wait_for_capability(self, call_id, invocation):
            return SimpleNamespace(
                status=CapabilityInvocationStatus.SUCCEEDED,
                semantic_result=None,
            )

    class Session:
        async def say(self, text, **kwargs):
            return None

    definition = RuntimeCapabilityDefinition(
        semantic_key="reservation.create_request",
        semantic_version=1,
        tool_name="reservation_create_request",
        description="Submit a reservation request.",
        announcement="I will submit your reservation request.",
        input_schema={"type": "object"},
    )
    tool = capability_tool(
        definition,
        Backend(),
        uuid4(),
        lambda **values: recorded.append(values),
    )

    result = await tool._func(  # type: ignore[attr-defined]
        SimpleNamespace(
            session=Session(), function_call=SimpleNamespace(call_id="tool-call")
        ),
        {},
    )

    assert result == {"status": "submitted"}
    assert recorded[0]["status"] == "ok"
    assert recorded[0]["error_type"] is None


@pytest.mark.asyncio
async def test_end_call_callback_records_native_tool_execution() -> None:
    recorded: list[dict[str, object]] = []
    end_call = build_agent_tools(
        runtime_context(),
        None,
        uuid4(),
        capability_recorder=lambda **values: recorded.append(values),
    )[1]
    ctx = SimpleNamespace()
    await end_call._on_tool_called(SimpleNamespace(ctx=ctx, arguments={}))  # type: ignore[attr-defined]
    await end_call._on_tool_completed(SimpleNamespace(ctx=ctx, output="goodbye"))  # type: ignore[attr-defined]
    assert recorded[0]["name"] == "call.end"
    assert recorded[0]["version"] == "1"
    assert recorded[0]["status"] == "ok"
    assert "arguments" not in recorded[0]


def test_committed_message_id_is_stable_and_preserves_interruption() -> None:
    call_id = uuid4()
    item = agents.llm.ChatMessage(
        id="item_1",
        role="assistant",
        content=["Hello"],
        interrupted=True,
    )
    event = agents.ConversationItemAddedEvent(item=item)
    first = message_from_event(call_id, event)
    second = message_from_event(call_id, event)
    assert first is not None
    assert second is not None
    assert first.payload.message_id == second.payload.message_id
    assert first.payload.role.value == "assistant"
    assert first.payload.interrupted
    assert first.payload.message_id
    assert MESSAGE_NAMESPACE


def test_azure_endpoint_accepts_resource_url_and_openai_v1_url() -> None:
    assert azure_endpoint("https://resource.openai.azure.com") == (
        "https://resource.openai.azure.com"
    )
    assert azure_endpoint("https://resource.openai.azure.com/openai/v1/") == (
        "https://resource.openai.azure.com"
    )


@pytest.mark.asyncio
async def test_provider_factory_uses_pinned_models_and_no_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    azure: dict[str, object] = {}
    original = openai.LLM.with_azure

    def capture_azure(**kwargs: object):
        azure.update(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(openai.LLM, "with_azure", capture_azure)
    session = create_agent_session(
        settings(), runtime_settings(), "voice-agent-prompt:test"
    )
    try:
        assert isinstance(session.stt, elevenlabs.STT)
        provider_stt = session.stt
        assert isinstance(session.llm, openai.LLM)
        assert isinstance(session.tts, elevenlabs.TTS)
        assert provider_stt._opts.model_id == "scribe_v2_realtime"
        assert str(provider_stt._opts.language_code) == "sk"
        assert provider_stt._opts.server_vad["vad_silence_threshold_secs"] == 0.35
        assert provider_stt._opts.server_vad["min_silence_duration_ms"] == 350
        assert session.vad is not None
        assert session.vad.model == "silero"
        assert session.vad._opts.min_speech_duration == 0.05
        assert session.vad._opts.min_silence_duration == 0.25
        assert session.vad._opts.activation_threshold == 0.5
        assert session.turn_detection == "stt"
        assert session._opts.turn_handling["endpointing"]["min_delay"] == 0.1
        assert session._opts.turn_handling["endpointing"]["max_delay"] == 0.7
        assert session._opts.turn_handling["preemptive_generation"]["enabled"] is True
        assert (
            session._opts.turn_handling["preemptive_generation"]["preemptive_tts"]
            is True
        )
        assert session.llm._opts.temperature == 0
        assert session.llm._opts.max_completion_tokens == 256
        assert azure["model"] == "model-a"
        assert azure["azure_deployment"] == "deployment"
        assert azure["azure_endpoint"] == "https://test.openai.azure.com"
        assert azure["api_version"] == "2025-01-01-preview"
        assert azure["api_key"] == "azure-key"
        assert azure["prompt_cache_key"] == "voice-agent-prompt:test"
        assert azure["max_completion_tokens"] == 256
        assert session.tts._opts.model == "eleven_flash_v2_5"
        assert session.tts._opts.voice_id == "voice-id"
        assert str(session.tts._opts.language) == "sk"
        assert session.tts._opts.word_tokenizer._config.min_sentence_len == 20
        assert session._tools == []
        assert session.conn_options.stt_conn_options.timeout == 10.0
        assert session.conn_options.stt_conn_options.max_retry == 3
        assert session.conn_options.llm_conn_options.timeout == 10.0
        assert session.conn_options.llm_conn_options.max_retry == 3
        assert session.conn_options.tts_conn_options.timeout == 10.0
        assert session.conn_options.tts_conn_options.max_retry == 3
        assert provider_stt._opts.api_key == "eleven-key"
        assert session.tts._opts.api_key == "eleven-key"
        assert provider_languages("sk-SK") == ("slk", "sk")
        with pytest.raises(ValueError):
            provider_languages("en-US")
    finally:
        await session.stt.aclose()
        await session.llm.aclose()
        await session.tts.aclose()


@pytest.mark.asyncio
async def test_provider_factory_passes_low_latency_tts_and_stt_candidates() -> None:
    runtime = runtime_settings(
        stt={
            "provider": "elevenlabs",
            "model": "scribe_v2_realtime",
            "interim_preflight": {
                "enabled": True,
                "min_transcript_chars": 20,
                "min_growth_chars": 12,
                "max_generations_per_turn": 2,
            },
            "server_vad": {
                "silence_threshold_seconds": 0.25,
                "activity_threshold": 0.35,
                "min_speech_ms": 100,
                "min_silence_ms": 250,
            },
        },
        tts={
            "provider": "elevenlabs",
            "model": "eleven_flash_v2_5",
            "voice_id": "voice-id",
            "min_sentence_chars": 12,
        },
    )
    session = create_agent_session(settings(), runtime, "voice-agent-prompt:test")
    try:
        assert isinstance(session.stt, InterimPreflightSTT)
        provider_stt = session.stt.wrapped_stt
        assert isinstance(provider_stt, elevenlabs.STT)
        assert provider_stt._opts.server_vad["vad_silence_threshold_secs"] == 0.25
        assert provider_stt._opts.server_vad["min_silence_duration_ms"] == 250
        assert session.tts._opts.word_tokenizer._config.min_sentence_len == 12
    finally:
        await session.stt.aclose()
        await session.llm.aclose()
        await session.tts.aclose()


@pytest.mark.asyncio
async def test_provider_factory_uses_runtime_logical_azure_model() -> None:
    session = create_agent_session(
        settings(),
        runtime_settings(
            llm={
                "provider": "azure_openai",
                "model": "model-b",
                "temperature": 0,
            }
        ),
        "voice-agent-prompt:test",
    )
    try:
        assert session.llm._opts.model == "model-b"
    finally:
        await session.stt.aclose()
        await session.llm.aclose()
        await session.tts.aclose()


@pytest.mark.parametrize(
    ("reason", "failure_reason"),
    [
        (agents.CloseReason.PARTICIPANT_DISCONNECTED, None),
        (agents.CloseReason.USER_INITIATED, None),
        (agents.CloseReason.TASK_COMPLETED, None),
        (agents.CloseReason.ERROR, "provider_session_error"),
        (agents.CloseReason.JOB_SHUTDOWN, "job_shutdown"),
    ],
)
def test_close_reason_mapping(
    reason: agents.CloseReason,
    failure_reason: str | None,
) -> None:
    assert close_failure_reason(reason) == failure_reason


@pytest.mark.asyncio
async def test_participant_timeout_fails_once(monkeypatch: pytest.MonkeyPatch) -> None:
    context = runtime_context()

    class FakeBackend:
        def __init__(self) -> None:
            self.failed: list[str] = []
            self.activated = False

        async def runtime_context(self, call_id):
            return context

        async def activate(self, call_id) -> None:
            self.activated = True

        async def complete(self, call_id, conversation_status: str) -> None:
            raise AssertionError("must not complete")

        async def fail(
            self,
            call_id,
            reason: str,
            conversation_status: str,
        ) -> None:
            self.failed.append(reason)

        async def aclose(self) -> None:
            return None

    class FakeSession:
        def on(self, event, callback):
            return callback

        async def start(self, agent, *, room, record) -> None:
            return None

        async def say(self, text) -> None:
            raise AssertionError("must not greet")

        async def aclose(self) -> None:
            return None

    backend = FakeBackend()
    monkeypatch.setattr("voice_agent.main.BackendClient", lambda _: backend)
    monkeypatch.setattr(
        "voice_agent.main.create_agent_session",
        lambda *_: FakeSession(),
    )

    class Context:
        job = SimpleNamespace(
            metadata=f'{{"call_session_id":"{context.call_session_id}"}}'
        )
        room = object()

        def add_shutdown_callback(self, callback) -> None:
            return None

        async def wait_for_participant(self, **kwargs):
            await asyncio.sleep(1)

    await run_job(
        Context(),  # type: ignore[arg-type]
        settings(participant_wait_timeout_seconds=0.001),
    )
    assert backend.failed == ["participant_timeout"]
    assert not backend.activated


@pytest.mark.asyncio
async def test_sip_claim_feeds_the_existing_runtime_and_session_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = runtime_context()
    order: list[str] = []

    class FakeBackend:
        async def claim_inbound_sip(self, request):
            order.append("claim")
            return InboundSipClaimResponse(
                call_session_id=context.call_session_id, created=True
            )

        async def runtime_context(self, call_id):
            order.append("runtime-context")
            assert call_id == context.call_session_id
            return context

        async def observe(self, call_id, observation_type: str) -> None:
            return None

        async def activate(self, call_id) -> None:
            return None

        async def complete(self, call_id, conversation_status: str) -> None:
            order.append("complete")

        async def fail(self, call_id, reason: str, conversation_status: str) -> None:
            raise AssertionError("successful SIP call must not fail")

        async def aclose(self) -> None:
            return None

    class FakeSession:
        def __init__(self) -> None:
            self.callbacks: dict[str, object] = {}
            self.record: object | None = None

        def on(self, event, callback):
            self.callbacks[event] = callback

        def off(self, event, callback):
            return None

        async def start(self, agent, *, room, record) -> None:
            self.record = record
            order.append("session-start")

        async def say(self, text) -> None:
            callback = self.callbacks["close"]
            callback(SimpleNamespace(reason=agents.CloseReason.TASK_COMPLETED))

        async def aclose(self) -> None:
            return None

    participant = SimpleNamespace(
        kind=rtc.ParticipantKind.PARTICIPANT_KIND_SIP,
        identity="sip-caller",
        attributes={
            "sip.callID": "SCL_run_job",
            "sip.callIDFull": "telnyx-run-job@example.net",
            "sip.phoneNumber": "+421900111222",
            "sip.trunkPhoneNumber": "+421552301410",
            "sip.trunkID": "ST_run_job",
            "sip.ruleID": "SDR_run_job",
        },
    )

    class Context:
        job = SimpleNamespace(metadata="")
        room = SimpleNamespace(name="sip-call-run-job")

        def add_shutdown_callback(self, callback) -> None:
            return None

        async def wait_for_participant(self, **kwargs):
            return participant

    backend = FakeBackend()
    sessions: list[FakeSession] = []

    def session_factory(*args):
        sessions.append(FakeSession())
        return sessions[0]

    monkeypatch.setattr("voice_agent.main.BackendClient", lambda _: backend)
    monkeypatch.setattr("voice_agent.main.create_agent_session", session_factory)
    await run_job(Context(), settings())  # type: ignore[arg-type]
    assert order[:3] == ["claim", "runtime-context", "session-start"]
    assert order[-1] == "complete"
    assert len(sessions) == 1
    assert sessions[0].record == {
        "audio": False,
        "traces": False,
        "logs": False,
        "transcript": False,
    }


@pytest.mark.asyncio
async def test_successful_handoff_relinquishes_without_completing_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = runtime_context().model_copy(
        update={
            "handoff_destinations": {"reception": {"description": "Reception requests"}}
        }
    )

    class Backend:
        def __init__(self) -> None:
            self.observations: list[tuple[str, str]] = []

        async def runtime_context(self, call_id):
            return context

        async def observe(
            self,
            call_id,
            observation_type: str,
            *,
            conversation_status: str = "complete",
        ) -> None:
            self.observations.append((observation_type, conversation_status))

        async def activate(self, call_id) -> None:
            return None

        async def complete(self, call_id, conversation_status: str) -> None:
            raise AssertionError("handoff must not complete the call")

        async def fail(self, call_id, reason: str, conversation_status: str) -> None:
            raise AssertionError("successful handoff must not fail the call")

        async def aclose(self) -> None:
            return None

    class Persistence:
        def __init__(self, backend, call_id) -> None:
            pass

        async def finish(self) -> bool:
            return True

        async def on_conversation_item_added(self, event) -> None:
            return None

    class Session:
        def __init__(self) -> None:
            self.callbacks: dict[str, object] = {}

        def on(self, event, callback):
            self.callbacks[event] = callback

        def off(self, event, callback):
            return None

        async def start(self, agent, *, room, record) -> None:
            return None

        async def say(self, text) -> None:
            callback = self.callbacks["close"]
            callback(SimpleNamespace(reason=agents.CloseReason.USER_INITIATED))

        async def aclose(self) -> None:
            return None

    class Context:
        job = SimpleNamespace(
            metadata=f'{{"call_session_id":"{context.call_session_id}"}}'
        )
        room = object()

        def add_shutdown_callback(self, callback) -> None:
            return None

        async def wait_for_participant(self, **kwargs):
            return object()

    backend = Backend()
    monkeypatch.setattr("voice_agent.main.BackendClient", lambda _: backend)
    monkeypatch.setattr("voice_agent.main.ConversationPersistence", Persistence)
    monkeypatch.setattr("voice_agent.main.create_agent_session", lambda *_: Session())

    def tools(runtime, client, call_id, on_handoff, capability_recorder=None):
        on_handoff()
        return []

    monkeypatch.setattr("voice_agent.main.build_agent_tools", tools)

    await run_job(Context(), settings())  # type: ignore[arg-type]

    assert backend.observations == [
        ("session_started", "complete"),
        ("agent_relinquished", "complete"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "close_reason",
    [
        agents.CloseReason.PARTICIPANT_DISCONNECTED,
        agents.CloseReason.USER_INITIATED,
    ],
)
async def test_session_close_terminalizes_while_session_is_alive(
    monkeypatch: pytest.MonkeyPatch,
    close_reason: agents.CloseReason,
) -> None:
    context = runtime_context()

    class FakeBackend:
        def __init__(self) -> None:
            self.completed: list[str] = []
            self.failed: list[str] = []

        async def runtime_context(self, call_id):
            return context

        async def observe(self, call_id, observation_type: str) -> None:
            return None

        async def activate(self, call_id) -> None:
            return None

        async def complete(self, call_id, conversation_status: str) -> None:
            self.completed.append(conversation_status)

        async def fail(self, call_id, reason: str, conversation_status: str) -> None:
            self.failed.append(reason)

        async def aclose(self) -> None:
            return None

    class FakeSession:
        def __init__(self) -> None:
            self.callbacks: dict[str, object] = {}
            self.greeted = asyncio.Event()

        def on(self, event, callback):
            self.callbacks[event] = callback

        def off(self, event, callback):
            return None

        async def start(self, agent, *, room, record) -> None:
            return None

        async def say(self, text) -> None:
            self.greeted.set()

        async def aclose(self) -> None:
            return None

    backend = FakeBackend()
    session = FakeSession()
    monkeypatch.setattr("voice_agent.main.BackendClient", lambda _: backend)
    monkeypatch.setattr("voice_agent.main.create_agent_session", lambda *_: session)

    class Context:
        job = SimpleNamespace(
            metadata=f'{{"call_session_id":"{context.call_session_id}"}}'
        )
        room = object()
        shutdown = None

        def add_shutdown_callback(self, callback) -> None:
            self.shutdown = callback

        async def wait_for_participant(self, **kwargs):
            return object()

    job = Context()
    task = asyncio.create_task(run_job(job, settings()))
    await session.greeted.wait()
    callback = session.callbacks["close"]
    callback(SimpleNamespace(reason=close_reason))
    assert job.shutdown is not None
    await job.shutdown("job_shutdown")
    await task

    assert backend.completed == ["complete"]
    assert backend.failed == []


@pytest.mark.asyncio
async def test_terminalizer_uses_the_first_terminal_signal_only() -> None:
    class Finalizer:
        def __init__(self) -> None:
            self.completed = 0
            self.failed: list[str] = []

        async def complete(self, conversation_status: str) -> None:
            self.completed += 1

        async def fail(self, reason: str, conversation_status: str) -> None:
            self.failed.append(reason)

    class Persistence:
        async def finish(self) -> bool:
            await asyncio.sleep(0)
            return True

    finalizer = Finalizer()
    terminalizer = SessionTerminalizer(finalizer, Persistence())  # type: ignore[arg-type]
    await asyncio.gather(
        terminalizer.terminalize(None),
        terminalizer.terminalize("job_shutdown"),
    )

    assert finalizer.completed == 1
    assert finalizer.failed == []
