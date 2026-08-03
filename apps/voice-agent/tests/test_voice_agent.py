import asyncio
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from contracts import VoiceAgentRuntimeContext
from livekit import agents
from livekit.plugins import elevenlabs, openai
from pydantic import ValidationError
from voice_agent.backend import BackendClient
from voice_agent.main import (
    assemble_instructions,
    close_failure_reason,
    on_request,
    parse_metadata,
    run_job,
)
from voice_agent.providers import azure_endpoint, create_agent_session, tts_language
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
        "elevenlabs_voice_id": "voice-id",
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
        room_name="call_test",
        locale="sk-SK",
        timezone="Europe/Bratislava",
        agent_display_name="Amelia",
        greeting="Dobry den",
        conversation_scope="property_only",
        prompt={
            "system_instructions": "System prompt",
            "tenant_instructions": "Tenant prompt",
            "knowledge_text": "Knowledge",
        },
    )


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

    accepted = Request(
        f'{{"call_session_id":"{uuid4()}"}}'
    )
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
        "System prompt\n\nTenant prompt\n\nKnowledge\n\n"
        "Locale: sk-SK\n\nTimezone: Europe/Bratislava\n\n"
        "Conversation scope: property_only"
    )


def test_azure_endpoint_accepts_resource_url_and_openai_v1_url() -> None:
    assert azure_endpoint("https://resource.openai.azure.com") == (
        "https://resource.openai.azure.com"
    )
    assert azure_endpoint("https://resource.openai.azure.com/openai/v1/") == (
        "https://resource.openai.azure.com"
    )


@pytest.mark.asyncio
async def test_provider_factory_uses_pinned_models_and_no_tools() -> None:
    session = create_agent_session(settings(), "sk-SK")
    try:
        assert isinstance(session.stt, elevenlabs.STT)
        assert isinstance(session.llm, openai.LLM)
        assert isinstance(session.tts, elevenlabs.TTS)
        assert session.stt._opts.model_id == "scribe_v2_realtime"
        assert str(session.stt._opts.language_code) == "sk"
        assert session.stt._opts.server_vad == {
            "vad_silence_threshold_secs": 1.0,
            "vad_threshold": 0.35,
            "min_speech_duration_ms": 100,
            "min_silence_duration_ms": 500,
        }
        assert session.vad is None
        assert session.turn_detection == "stt"
        assert session.tts._opts.model == "eleven_flash_v2_5"
        assert session.tts._opts.voice_id == "voice-id"
        assert str(session.tts._opts.language) == "sk"
        assert session._tools == []
        assert session.conn_options.stt_conn_options.timeout == 10.0
        assert session.conn_options.stt_conn_options.max_retry == 3
        assert tts_language("sk-SK") == "sk"
        with pytest.raises(ValueError):
            tts_language("en-US")
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

        async def complete(self, call_id) -> None:
            raise AssertionError("must not complete")

        async def fail(self, call_id, reason: str) -> None:
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
