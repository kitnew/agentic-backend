import asyncio
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from contracts import (
    EffectiveVoiceRuntime,
    RuntimeCapabilityDefinition,
    VoiceAgentRuntimeContext,
)
from livekit import agents
from livekit.plugins import elevenlabs, openai
from pydantic import ValidationError
from voice_agent.backend import BackendClient
from voice_agent.calculator import calculate, calculator_tool
from voice_agent.main import (
    assemble_instructions,
    build_agent_tools,
    capability_tool,
    close_failure_reason,
    on_request,
    parse_metadata,
    run_job,
)
from voice_agent.persistence import MESSAGE_NAMESPACE, message_from_event
from voice_agent.providers import (
    azure_endpoint,
    create_agent_session,
    provider_languages,
)
from voice_agent.settings import VoiceAgentSettings


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
        "azure_openai_model": "model-a",
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
            "server_vad": {
                "silence_threshold_seconds": 0.5,
                "activity_threshold": 0.35,
                "min_speech_ms": 100,
                "min_silence_ms": 500,
            },
        },
        "tts": {
            "provider": "elevenlabs",
            "model": "eleven_flash_v2_5",
            "voice_id": "voice-id",
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
async def test_on_request_accepts_only_valid_metadata() -> None:
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
    assert instructions == (
        "System prompt\n\nProfile prompt\n\nTenant prompt\n\n"
        "Locale: sk-SK\n\nTimezone: Europe/Bratislava\n\n"
        "Conversation scope: property_only\n\n"
        "Use a capability tool when its inputs are known. Do not promise success "
        "before its result. reservation_submit_request submits a request; it never "
        "confirms a reservation.\n\n"
        "Use the calculator whenever exact arithmetic is required. It performs one "
        "operation per call; decompose multi-step calculations into sequential calls "
        "and pass each result forward. It does not interpret business meaning. "
        "percentage(A, B) means B percent of A.\n\nKnowledge"
    )


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

    assert calculate(CalculatorRequest(operation=operation, operands=operands)) == expected


@pytest.mark.parametrize("operand", ["NaN", "Infinity", "1 + 2", ""])
def test_calculator_rejects_invalid_decimal_values(operand: str) -> None:
    from contracts import CalculatorRequest

    with pytest.raises(ValidationError, match="decimal values"):
        CalculatorRequest(operation="add", operands=[operand, "1"])


@pytest.mark.asyncio
async def test_calculator_tool_returns_result_and_structured_failures() -> None:
    tool = calculator_tool()
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


def test_calculator_is_always_added_before_tenant_tools() -> None:
    context = runtime_context()
    tools = build_agent_tools(context.model_copy(update={"capabilities": []}), None, uuid4())  # type: ignore[arg-type]
    assert len(tools) == 1
    assert tools[0]._info.name == "calculator"  # type: ignore[attr-defined]
    assert "one arithmetic operation per call" in tools[0]._info.raw_schema["description"]  # type: ignore[attr-defined]


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
    session = create_agent_session(settings(), runtime_settings())
    try:
        assert isinstance(session.stt, elevenlabs.STT)
        assert isinstance(session.llm, openai.LLM)
        assert isinstance(session.tts, elevenlabs.TTS)
        assert session.stt._opts.model_id == "scribe_v2_realtime"
        assert str(session.stt._opts.language_code) == "sk"
        assert session.vad is not None
        assert session.vad.model == "silero"
        assert session.vad._opts.min_speech_duration == 0.05
        assert session.vad._opts.min_silence_duration == 0.25
        assert session.vad._opts.activation_threshold == 0.5
        assert session.turn_detection == "stt"
        assert session._opts.turn_handling["endpointing"]["min_delay"] == 0.1
        assert session._opts.turn_handling["endpointing"]["max_delay"] == 0.7
        assert session.llm._opts.temperature == 0
        assert azure["model"] == "model-a"
        assert azure["azure_deployment"] == "deployment"
        assert azure["azure_endpoint"] == "https://test.openai.azure.com"
        assert azure["api_version"] == "2025-01-01-preview"
        assert azure["api_key"] == "azure-key"
        assert session.tts._opts.model == "eleven_flash_v2_5"
        assert session.tts._opts.voice_id == "voice-id"
        assert str(session.tts._opts.language) == "sk"
        assert session._tools == []
        assert session.conn_options.stt_conn_options.timeout == 10.0
        assert session.conn_options.stt_conn_options.max_retry == 3
        assert session.conn_options.llm_conn_options.timeout == 10.0
        assert session.conn_options.llm_conn_options.max_retry == 3
        assert session.conn_options.tts_conn_options.timeout == 10.0
        assert session.conn_options.tts_conn_options.max_retry == 3
        assert session.stt._opts.api_key == "eleven-key"
        assert session.tts._opts.api_key == "eleven-key"
        assert provider_languages("sk-SK") == ("slk", "sk")
        with pytest.raises(ValueError):
            provider_languages("en-US")
    finally:
        await session.stt.aclose()
        await session.llm.aclose()
        await session.tts.aclose()


def test_provider_factory_rejects_unbound_logical_azure_model() -> None:
    with pytest.raises(ValueError, match="is not bound"):
        create_agent_session(
            settings(),
            runtime_settings(
                llm={
                    "provider": "azure_openai",
                    "model": "model-b",
                    "temperature": 0,
                }
            ),
        )


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

        async def start(self, agent, *, room) -> None:
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

        async def wait_for_participant(self, **kwargs):
            await asyncio.sleep(1)

    await run_job(
        Context(),  # type: ignore[arg-type]
        settings(participant_wait_timeout_seconds=0.001),
    )
    assert backend.failed == ["participant_timeout"]
    assert not backend.activated
