import asyncio
import inspect
from datetime import datetime as RealDatetime
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import jwt
import pytest
import voice_agent.main as voice_main
from contracts import (
    CapabilityInvocationStatus,
    HandoffState,
    HumanHandoffResponse,
    InboundSipClaimResponse,
    VoiceExecutionContext,
)
from livekit import agents, rtc
from livekit.agents.beta.tools import EndCallTool
from livekit.agents.utils import is_given
from livekit.plugins import elevenlabs, openai, soniox
from livekit.plugins.openai import realtime
from pydantic import ValidationError
from voice_agent.backend import BackendClient
from voice_agent.calculator import calculate, calculator_tool
from voice_agent.event_delivery import MESSAGE_NAMESPACE, message_from_event
from voice_agent.handoff import HandoffAttempt
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
    send_greeting,
)
from voice_agent.providers import (
    USER_AWAY_TIMEOUT,
    _create_tts,
    azure_endpoint,
    create_agent_session,
    create_half_cascade_session,
    create_realtime_session,
    llm_behavior_options,
    provider_languages,
)
from voice_agent.settings import VoiceAgentSettings
from voice_agent.stt_endpointing import LocalVadCommitSTT


def settings(**overrides: object) -> VoiceAgentSettings:
    values: dict[str, object] = {
        "livekit_url": "ws://livekit:7880",
        "livekit_api_key": "test-key",
        "livekit_api_secret": "test-secret",
        "livekit_agent_name": "hospitality-voice-agent",
        "backend_core_url": "http://backend:8000",
        "internal_api_audience": "backend-core",
        "voice_agent_service_secret": "v" * 32,
    }
    values.update(overrides)
    return VoiceAgentSettings.model_validate(values)


class FakeSpeechHandle:
    def __init__(self, playout: asyncio.Future[None]) -> None:
        self.playout = playout

    async def wait_for_playout(self) -> None:
        await self.playout


def test_inactivity_policy_is_25_seconds_total() -> None:
    assert USER_AWAY_TIMEOUT == 10.0
    assert voice_main.INACTIVITY_TOTAL_TIMEOUT - USER_AWAY_TIMEOUT == 15.0


def runtime_context() -> VoiceExecutionContext:
    return VoiceExecutionContext(
        execution_id=uuid4(),
        agent={
            "display_name": "Amelia",
            "role": "Hotel concierge",
            "grammatical_gender": "feminine",
            "greeting": "Dobry den",
            "conversation_scope": "property_only",
        },
        business={
            "name": "Grand Hotel",
            "type": "hotel",
            "address": "Main Street 1",
            "phones": ["+421900123456"],
            "emails": ["hello@example.com"],
            "website": "https://example.com",
            "links": [{"label": "Instagram", "value": "@grandhotel"}],
            "default_locale": "sk-SK",
            "timezone": "Europe/Bratislava",
        },
        architecture="cascade",
        prompts={
            "system": "System prompt",
            "profile": "Profile prompt",
            "interaction": "Interaction prompt",
            "tenant": "Tenant prompt",
            "knowledge": "Knowledge",
        },
        runtime=target_runtime(),
        actions=[],
        handoff=[],
    )


def target_runtime() -> dict[str, object]:
    policy = {
        "interruption": {
            "enabled": True,
            "min_duration_seconds": 0.5,
            "min_words": 0,
            "false_interruption_timeout_seconds": 2,
            "resume_after_false_interruption": True,
        },
        "response_scheduling": {
            "preemptive_generation": False,
            "preemptive_tts": False,
        },
    }
    return {
        "llm": {
            "provider_kind": "azure_openai",
            "deployment_config": {"model": "model-a"},
            "connection_config": {},
            "max_completion_tokens": 256,
            "temperature": 0,
            "reasoning_effort": None,
            **policy,
        },
        "stt": {
            "provider_kind": "elevenlabs",
            "deployment_config": {"model_id": "scribe_v2_realtime"},
            "connection_config": {},
            "speech_hints": {"keyterms": {"values": []}},
            "speech_activity": {
                "min_speech_seconds": 0.05,
                "min_silence_seconds": 0.25,
                "activation_threshold": 0.5,
            },
            "commit": {
                "strategy": "provider_vad",
                "provider_vad": {
                    "silence_threshold_seconds": 0.35,
                    "threshold": 0.35,
                    "min_speech_ms": 100,
                    "min_silence_ms": 350,
                },
            },
            "endpointing": {"min_delay_seconds": 0.1, "max_delay_seconds": 0.7},
        },
        "tts": {
            "provider_kind": "elevenlabs",
            "deployment_config": {"model_id": "eleven_flash_v2_5"},
            "connection_config": {},
            "voice": "voice-id",
            "tokenizer": {
                "strategy": "sentence",
                "min_sentence_chars": 20,
                "min_phrase_chars": 10,
            },
        },
        "realtime": {},
    }


def runtime_action(
    key: str, *, announcement: str = "I will process that now."
) -> dict[str, object]:
    return {
        "key": key,
        "phase": "runtime",
        "definition": {
            "description": "Execute the requested action.",
            "announcement": announcement,
            "agent_input_schema": {"type": "object"},
            "business_policy": {},
        },
        "execution_plan": {},
        "integration": {"semantic_key": "test"},
    }


def runtime_settings(**overrides: object) -> dict[str, object]:
    runtime = target_runtime()
    runtime["locale"] = "sk-SK"
    llm = runtime["llm"]
    stt = runtime["stt"]
    tts = runtime["tts"]
    assert isinstance(llm, dict) and isinstance(stt, dict) and isinstance(tts, dict)
    llm["deployment_config"] = {
        "model": "model-a",
        "deployment_name": "deployment",
        "api_version": "2025-01-01-preview",
    }
    llm["connection_config"] = {"endpoint": "https://test.openai.azure.com"}
    if isinstance(value := overrides.get("llm"), dict):
        llm.update(
            {
                key: item
                for key, item in value.items()
                if key not in {"provider", "model"}
            }
        )
        llm["provider_kind"] = value.get("provider", llm["provider_kind"])
        llm["deployment_config"]["model"] = value.get(
            "model", llm["deployment_config"]["model"]
        )
    if isinstance(value := overrides.get("stt"), dict):
        stt["provider_kind"] = value.get("provider", stt["provider_kind"])
        stt["deployment_config"]["model_id"] = value.get(
            "model", stt["deployment_config"]["model_id"]
        )
        stt["speech_hints"]["keyterms"]["values"] = value.get("keyterms", [])
        vad = value.get("server_vad", {})
        stt["commit"]["provider_vad"] = {
            "silence_threshold_seconds": vad.get("silence_threshold_seconds", 0.35),
            "threshold": vad.get("activity_threshold", 0.35),
            "min_speech_ms": vad.get("min_speech_ms", 100),
            "min_silence_ms": vad.get("min_silence_ms", 350),
        }
    if isinstance(value := overrides.get("tts"), dict):
        tts["provider_kind"] = value.get("provider", tts["provider_kind"])
        tts["deployment_config"]["model_id"] = value.get(
            "model", tts["deployment_config"]["model_id"]
        )
        tts["voice"] = value.get("voice_id", tts["voice"])
        tts["tokenizer"]["min_sentence_chars"] = value.get("min_sentence_chars", 20)
        tts["tokenizer"]["strategy"] = value.get("strategy", "sentence")
        tts["tokenizer"]["min_phrase_chars"] = value.get("min_phrase_chars", 10)
    if isinstance(value := overrides.get("local_vad"), dict):
        stt["speech_activity"] = value
    if isinstance(value := overrides.get("turn"), dict):
        stt["endpointing"] = {
            "min_delay_seconds": value.get("min_endpointing_delay_seconds", 0.1),
            "max_delay_seconds": value.get("max_endpointing_delay_seconds", 0.7),
        }
    if isinstance(value := overrides.get("interruption"), dict):
        llm["interruption"] = value
    if isinstance(value := overrides.get("response_scheduling"), dict):
        llm["response_scheduling"] = value
    return runtime


def test_llm_behavior_options_follow_runtime_model() -> None:
    reasoning = runtime_settings(
        llm={
            "provider": "azure_openai",
            "model": "gpt-5.6-terra",
            "max_completion_tokens": 256,
            "temperature": None,
            "reasoning_effort": "none",
        }
    )
    assert llm_behavior_options(reasoning) == {"reasoning_effort": "none"}

    classic = runtime_settings(
        llm={
            "provider": "azure_openai",
            "model": "gpt-4o-mini",
            "max_completion_tokens": 256,
            "temperature": 0,
            "reasoning_effort": None,
        }
    )
    assert llm_behavior_options(classic) == {"temperature": 0}


@pytest.mark.parametrize("effort", ["none", "low", "medium", "high", "xhigh", "max"])
def test_reasoning_effort_survives_azure_deployment_alias(effort: str) -> None:
    runtime = runtime_settings(
        llm={
            "provider": "azure_openai",
            "model": "hotel-fast-alias",
            "temperature": None,
            "reasoning_effort": effort,
        }
    )

    assert llm_behavior_options(runtime) == {"reasoning_effort": effort}


def test_provider_default_omits_reasoning_effort() -> None:
    runtime = runtime_settings(
        llm={
            "provider": "azure_openai",
            "model": "gpt-5.6-terra",
            "reasoning_effort": None,
        }
    )

    assert runtime["llm"]["reasoning_effort"] is None  # type: ignore[index]
    assert llm_behavior_options(runtime) == {}


@pytest.mark.asyncio
async def test_provider_default_is_omitted_from_livekit_request_kwargs() -> None:
    runtime = runtime_settings(
        llm={
            "provider": "azure_openai",
            "model": "gpt-5.6-terra",
            "reasoning_effort": None,
        }
    )
    options = llm_behavior_options(runtime)
    provider = openai.LLM(model="gpt-5.6-terra", api_key="unit-test", **options)
    try:
        stream = provider.chat(chat_ctx=agents.llm.ChatContext())

        assert "reasoning_effort" not in stream._extra_kwargs
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_explicit_none_reaches_livekit_openai_request_kwargs() -> None:
    runtime = runtime_settings(
        llm={
            "provider": "azure_openai",
            "model": "hotel-fast-alias",
            "temperature": None,
            "reasoning_effort": "none",
        }
    )
    options = llm_behavior_options(runtime)
    provider = openai.LLM(model="hotel-fast-alias", api_key="unit-test", **options)
    try:
        stream = provider.chat(chat_ctx=agents.llm.ChatContext())

        assert stream._extra_kwargs["reasoning_effort"] == "none"
    finally:
        await provider.aclose()


def test_elevenlabs_public_stt_api_exposes_realtime_keyterms() -> None:
    assert "keyterms" in inspect.signature(elevenlabs.STT).parameters


def test_realtime_factory_uses_snapshot_runtime_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def model(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(realtime, "RealtimeModel", model)
    monkeypatch.setattr(agents, "AgentSession", lambda **kwargs: kwargs)
    session = create_realtime_session(
        settings(),
        {
            "model": {
                "deployment_config": {
                    "model": "realtime-model",
                    "deployment_name": "realtime-deployment",
                    "api_version": "2026-02-01",
                },
                "connection_config": {"endpoint": "https://realtime.example"},
            },
            "voice": "custom-voice",
            "input_transcription": {
                "deployment_config": {"model": "gpt-live-transcribe"},
                "language": "sk-SK",
            },
            "turn_completion": {"strategy": "semantic_vad", "eagerness": "medium"},
            "interruption": {"enabled": True},
            "stt": {
                "provider_kind": "elevenlabs",
                "deployment_config": {"model_id": "transcribe-model"},
                "language": "sk",
            },
        },
        {"model": "secret", "stt": "eleven-secret"},
    )
    assert captured["azure_deployment"] == "realtime-deployment"
    assert captured["base_url"] == "https://realtime.example/openai"
    assert captured["api_version"] == "2026-02-01"
    assert captured["voice"] == "custom-voice"
    assert captured["input_audio_transcription"] == {
        "model": "gpt-live-transcribe",
        "language": "sk",
    }
    assert captured["turn_detection"].type == "semantic_vad"  # type: ignore[union-attr]
    assert captured["turn_detection"].interrupt_response is True  # type: ignore[union-attr]
    assert session["vad"] is None
    assert session["user_away_timeout"] == 10.0
    assert isinstance(session["stt"], elevenlabs.STT)
    assert session["stt"].model == "transcribe-model"
    assert session["stt"].provider == "ElevenLabs"


def test_realtime_factory_uses_azure_v1_endpoint_without_api_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def model(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(realtime, "RealtimeModel", model)
    monkeypatch.setattr(agents, "AgentSession", lambda **kwargs: kwargs)
    create_realtime_session(
        settings(),
        {
            "model": {
                "deployment_config": {"deployment_name": "gpt-realtime-2.1-mini"},
                "connection_config": {
                    "endpoint": "https://realtime.example/openai/v1",
                    "api_version": "2026-07-07",
                },
            },
            "voice": "marin",
            "input_transcription": {
                "deployment_config": {"model": "gpt-live-transcribe"},
                "language": "sk-SK",
            },
            "turn_completion": {"strategy": "semantic_vad", "eagerness": "medium"},
            "interruption": {"enabled": True},
            "stt": {
                "provider_kind": "elevenlabs",
                "deployment_config": {"model_id": "scribe_v2_realtime"},
                "language": "sk",
            },
        },
        {"model": "secret", "stt": "eleven-secret"},
    )

    assert captured["base_url"] == "https://realtime.example/openai/v1"
    assert captured["api_version"] is None
    assert captured["azure_deployment"] == "gpt-realtime-2.1-mini"


def test_realtime_factory_rejects_unsupported_standalone_stt_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(realtime, "RealtimeModel", lambda **kwargs: object())
    with pytest.raises(ValueError, match="unsupported STT provider: deepgram"):
        create_realtime_session(
            settings(),
            {
                "model": {
                    "deployment_config": {"deployment_name": "realtime-deployment"},
                    "connection_config": {"endpoint": "https://realtime.example"},
                },
                "turn_completion": {
                    "strategy": "server_vad",
                    "silence_duration_ms": 500,
                },
                "interruption": {"enabled": True},
                "stt": {
                    "provider_kind": "deepgram",
                    "deployment_config": {"model_id": "nova-3"},
                    "language": "sk",
                },
            },
            {"model": "secret", "stt": "eleven-secret"},
        )


def test_realtime_factory_uses_configured_azure_stt_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    standalone_stt = object()
    monkeypatch.setattr(realtime, "RealtimeModel", lambda **kwargs: object())
    monkeypatch.setattr(
        openai.STT,
        "with_azure",
        lambda **kwargs: captured.update(kwargs) or standalone_stt,
    )
    monkeypatch.setattr(agents, "AgentSession", lambda **kwargs: kwargs)

    session = create_realtime_session(
        settings(),
        {
            "model": {
                "deployment_config": {"deployment_name": "realtime-deployment"},
                "connection_config": {"endpoint": "https://realtime.example"},
            },
            "turn_completion": {"strategy": "server_vad"},
            "input_transcription": {
                "deployment_config": {"model": "gpt-live-transcribe"},
                "language": "sk-SK",
            },
            "interruption": {"enabled": True},
            "stt": {
                "provider_kind": "azure_openai",
                "connection_config": {
                    "endpoint": "https://transcription.example",
                    "api_version": "2026-03-01",
                },
                "deployment_config": {
                    "deployment_name": "transcription-deployment",
                    "model": "gpt-live-transcribe",
                },
                "language": "sk-SK",
            },
        },
        {"model": "realtime-secret", "stt": "stt-secret"},
    )

    assert session["stt"] is standalone_stt
    assert captured == {
        "api_key": "stt-secret",
        "azure_endpoint": "https://transcription.example",
        "azure_deployment": "transcription-deployment",
        "api_version": "2026-03-01",
        "model": "gpt-live-transcribe",
        "language": "sk",
    }


def test_realtime_factory_normalizes_regional_locale_for_standalone_stt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        realtime,
        "RealtimeModel",
        lambda **kwargs: captured.update(kwargs) or object(),
    )
    monkeypatch.setattr(agents, "AgentSession", lambda **kwargs: kwargs)
    session = create_realtime_session(
        settings(),
        {
            "model": {
                "deployment_config": {"deployment_name": "realtime-deployment"},
                "connection_config": {"endpoint": "https://realtime.example"},
            },
            "voice": "marin",
            "input_transcription": {
                "deployment_config": {"model": "gpt-live-transcribe"},
                "language": "sk-SK",
            },
            "turn_completion": {"strategy": "semantic_vad", "eagerness": "medium"},
            "interruption": {"enabled": True},
            "stt": {
                "provider_kind": "elevenlabs",
                "deployment_config": {"model_id": "transcribe-model"},
                "language": "sk-SK",
            },
        },
        {"model": "secret", "stt": "eleven-secret"},
    )

    assert captured["input_audio_transcription"] == {
        "model": "gpt-live-transcribe",
        "language": "sk",
    }
    assert isinstance(session["stt"], elevenlabs.STT)
    assert session["stt"].model == "transcribe-model"


def test_half_cascade_factory_uses_text_realtime_and_configured_tts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_model: dict[str, object] = {}
    captured_tts: dict[str, object] = {}

    monkeypatch.setattr(
        realtime,
        "RealtimeModel",
        lambda **kwargs: captured_model.update(kwargs) or object(),
    )
    monkeypatch.setattr(
        elevenlabs,
        "TTS",
        lambda **kwargs: captured_tts.update(kwargs) or object(),
    )
    monkeypatch.setattr(agents, "AgentSession", lambda **kwargs: kwargs)

    session = create_half_cascade_session(
        settings(),
        {
            "locale": "sk-SK",
            "model": {
                "deployment_config": {
                    "deployment_name": "realtime-deployment",
                    "model": "realtime-model",
                },
                "connection_config": {"endpoint": "https://realtime.example"},
            },
            "stt": {
                "provider_kind": "elevenlabs",
                "deployment_config": {"model_id": "transcribe-model"},
                "language": "sk",
            },
            "input_transcription": {
                "deployment_config": {"model": "gpt-live-transcribe"},
                "language": "sk-SK",
            },
            "tts": {
                "provider_kind": "elevenlabs",
                "deployment_config": {"model_id": "eleven_flash_v2_5"},
                "connection_config": {},
                "voice": "tts-voice",
            },
            "turn_completion": {
                "strategy": "server_vad",
                "activation_threshold": 0.4,
                "silence_duration_ms": 250,
            },
            "interruption": {"enabled": True},
        },
        {
            "model": "realtime-secret",
            "stt": "realtime-secret",
            "tts": "tts-secret",
        },
    )

    assert captured_model["modalities"] == ["text"]
    assert captured_model["input_audio_transcription"] == {
        "model": "gpt-live-transcribe",
        "language": "sk",
    }
    assert "voice" not in captured_model
    assert captured_model["api_key"] == "realtime-secret"
    assert captured_model["turn_detection"].type == "server_vad"  # type: ignore[union-attr]
    assert captured_model["turn_detection"].interrupt_response is True  # type: ignore[union-attr]
    assert captured_tts["api_key"] == "tts-secret"
    assert captured_tts["model"] == "eleven_flash_v2_5"
    assert captured_tts["voice_id"] == "tts-voice"
    assert isinstance(session["stt"], elevenlabs.STT)
    assert session["stt"].model == "transcribe-model"
    assert session["vad"] is None
    assert session["llm"] is not None
    assert session["tts"] is not None
    assert session["user_away_timeout"] == 10.0
    assert session["turn_handling"] == {
        "turn_detection": "realtime_llm",
        "interruption": {"enabled": True},
    }


@pytest.mark.parametrize("model", ["eleven_v3", "eleven_v3_conversational"])
def test_eleven_v3_tts_disables_auto_mode(model: str) -> None:
    tts = _create_tts(
        {
            "deployment_config": {"model_id": model},
            "voice": "voice-id",
        },
        "sk",
        "eleven-key",
    )

    assert tts._opts.auto_mode is False


def test_phrase_tts_uses_phrase_tokenizer_without_changing_v3_auto_mode() -> None:
    tts = _create_tts(
        {"deployment_config": {"model_id": "eleven_v3_conversational"}, "voice": "v"},
        "sk",
        "key",
        tokenizer_strategy="phrase",
        min_phrase_chars=10,
    )

    assert tts._opts.auto_mode is False
    assert tts._opts.word_tokenizer.tokenize("Dobrý deň, preverím dostupnosť.") == [
        "Dobrý deň,",
        "preverím dostupnosť.",
    ]


@pytest.mark.parametrize("model", ["eleven_flash_v2_5", "eleven_turbo_v2_5"])
def test_non_v3_tts_keeps_auto_mode_default(model: str) -> None:
    tts = _create_tts(
        {
            "deployment_config": {"model_id": model},
            "voice": "voice-id",
        },
        "sk",
        "eleven-key",
    )

    assert tts._opts.auto_mode is True


@pytest.mark.asyncio
async def test_half_cascade_installed_livekit_pipeline_has_audio_input_text_output_and_tts() -> (
    None
):
    session = create_half_cascade_session(
        settings(),
        {
            "locale": "sk-SK",
            "model": {
                "deployment_config": {
                    "deployment_name": "realtime-deployment",
                    "model": "realtime-model",
                },
                "connection_config": {"endpoint": "https://realtime.example"},
            },
            "stt": {
                "provider_kind": "elevenlabs",
                "deployment_config": {"model_id": "transcribe-model"},
                "language": "sk",
            },
            "input_transcription": {
                "deployment_config": {"model": "gpt-live-transcribe"},
                "language": "sk-SK",
            },
            "tts": {
                "provider_kind": "elevenlabs",
                "deployment_config": {"model_id": "eleven_flash_v2_5"},
                "connection_config": {},
                "voice": "tts-voice",
            },
            "turn_completion": {"strategy": "semantic_vad", "eagerness": "medium"},
            "interruption": {"enabled": True},
        },
        {
            "model": "realtime-secret",
            "stt": "realtime-secret",
            "tts": "tts-secret",
        },
    )
    try:
        assert isinstance(session.stt, elevenlabs.STT)
        assert session.stt.model == "transcribe-model"
        assert isinstance(session.llm, realtime.RealtimeModel)
        assert not session.llm.capabilities.audio_output
        assert isinstance(session.tts, elevenlabs.TTS)
    finally:
        await session.llm.aclose()
        await session.tts.aclose()


@pytest.mark.asyncio
async def test_elevenlabs_realtime_connection_serializes_keyterms() -> None:
    class Session:
        closed = False

        def __init__(self) -> None:
            self.url = ""

        async def ws_connect(self, url: str, **_: object) -> object:
            self.url = url
            return object()

    http_session = Session()
    provider = elevenlabs.STT(
        api_key="eleven-key",
        http_session=http_session,  # type: ignore[arg-type]
        keyterms=["Penzión Grand", "Kováčska"],
        language_code="slk",
        model="scribe_v2_realtime",
    )
    stream = provider.stream()
    try:
        await stream._connect_ws()  # type: ignore[attr-defined]
        assert parse_qs(urlsplit(http_session.url).query)["keyterms"] == [
            "Penzión Grand",
            "Kováčska",
        ]
    finally:
        await stream.aclose()
        await provider.aclose()


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


def test_prompt_assembly_uses_only_runtime_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FixedDatetime:
        @classmethod
        def now(cls, timezone):
            return RealDatetime(2026, 9, 17, 14, 5, tzinfo=timezone)

    monkeypatch.setattr(voice_main, "datetime", FixedDatetime)
    context = runtime_context()
    instructions = assemble_instructions(context)
    assert (
        instructions
        == """[System instructions]
System prompt

[Profile instructions]
Profile prompt

[Interaction instructions]
Interaction prompt

[Tenant instructions]
Tenant prompt

[Agent context]
Display name: Amelia
Role: Hotel concierge
Grammatical gender: feminine
Conversation scope: property_only

[Business context]
Name: Grand Hotel
Type: hotel
Address: Main Street 1
Phones:
- +421900123456
Emails:
- hello@example.com
Website: https://example.com
Links:
- Instagram: @grandhotel
[Localization]
Default locale: sk-SK
Timezone: Europe/Bratislava

[Tenant knowledge]
Knowledge

[Dynamic context]
Current local date: 2026-09-17
Current local time: 14:05"""
    )
    assert context.agent.greeting not in instructions
    assert "Use the calculator" not in instructions


def test_prompt_assembly_includes_caller_phone_from_runtime_metadata() -> None:
    context = runtime_context().model_copy(
        update={"metadata": {"caller_phone": "+15555550100"}}
    )

    instructions = assemble_instructions(context)

    assert "Caller phone number: +15555550100" in instructions


def test_capability_tool_exposes_raw_phone_and_optional_country() -> None:
    action = {
        "key": "reservation.create",
        "definition": {
            "description": "Create reservation",
            "agent_input_schema": {
                "type": "object",
                "properties": {
                    "phone_number": {"type": "string", "minLength": 1},
                    "phone_country": {"type": "string", "pattern": "^[A-Z]{2}$"},
                },
                "required": ["phone_number"],
                "additionalProperties": False,
            },
        },
    }
    tool = capability_tool(action, object(), uuid4())  # type: ignore[arg-type]
    schema = tool._info.raw_schema["parameters"]  # type: ignore[attr-defined]
    assert schema["required"] == ["phone_number"]
    assert "pattern" not in schema["properties"]["phone_number"]


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
async def test_handoff_tool_is_semantic_and_starts_attempt() -> None:
    attempt_id = uuid4()

    class Backend:
        def __init__(self) -> None:
            self.requests: list[object] = []

        async def transfer_to_human(self, call_id, request):
            self.requests.append(request)
            return HumanHandoffResponse(
                status="dialing",
                destination=request.destination,
                attempt_id=attempt_id,
                participant_identity="handoff-participant",
            )

    class Controller:
        def __init__(self) -> None:
            self.started: list[tuple[object, object]] = []

        async def start(self, response, session) -> None:
            self.started.append((response, session))

    call_id = uuid4()
    backend = Backend()
    controller = Controller()
    recorded: list[dict[str, object]] = []
    runtime = VoiceExecutionContext.model_validate(
        {
            **runtime_context().model_dump(),
            "handoff": [
                {
                    "destination_key": "reception",
                    "description": "Reservations and reception requests",
                }
            ],
        }
    )
    tools = build_agent_tools(runtime, backend, call_id)  # type: ignore[arg-type]
    assert [tools[0]._info.name, tools[1].id, tools[2]._info.name] == [  # type: ignore[attr-defined]
        "calculator",
        "end_call",
        "transfer_to_human",
    ]
    tool = handoff_tool(  # type: ignore[arg-type]
        runtime,
        backend,
        call_id,
        controller,
        lambda **values: recorded.append(values),
    )
    schema = tool._info.raw_schema  # type: ignore[attr-defined]
    assert schema["parameters"]["properties"]["destination"]["enum"] == ["reception"]
    assert "phone" not in str(schema).lower()
    session = SimpleNamespace()
    result = await tool._func(  # type: ignore[attr-defined]
        SimpleNamespace(
            session=session,
            function_call=SimpleNamespace(call_id="tool-handoff-1"),
        ),
        {"destination": "reception", "reason": "Guest asked for reception"},
    )
    assert result == {
        "status": "dialing",
        "destination": "reception",
        "attempt_id": str(attempt_id),
        "participant_identity": "handoff-participant",
        "error_code": None,
        "message": "The handoff was successfully initiated. Waiting for confirmation.",
    }
    assert len(controller.started) == 1
    started, started_session = controller.started[0]
    assert started.attempt_id == attempt_id
    assert started_session is session
    assert backend.requests[0].destination == "reception"  # type: ignore[union-attr]
    assert len(recorded) == 1
    assert recorded[0]["name"] == "transfer_to_human"
    assert recorded[0]["status"] == "ok"


@pytest.mark.asyncio
async def test_handoff_dialing_result_tells_model_to_wait() -> None:
    attempt_id = uuid4()

    class Backend:
        async def transfer_to_human(self, call_id, request):
            return HumanHandoffResponse(
                status="dialing",
                destination=request.destination,
                attempt_id=attempt_id,
                participant_identity="handoff-participant",
            )

    runtime = runtime_context().model_copy(
        update={
            "handoff": [{"destination_key": "reception", "description": "Reception"}]
        }
    )
    tool = handoff_tool(runtime, Backend(), uuid4())
    result = await tool._func(  # type: ignore[attr-defined]
        SimpleNamespace(
            session=SimpleNamespace(),
            function_call=SimpleNamespace(call_id="tool-handoff-2"),
        ),
        {"destination": "reception"},
    )
    assert result == {
        "status": "dialing",
        "destination": "reception",
        "attempt_id": str(attempt_id),
        "participant_identity": "handoff-participant",
        "error_code": None,
        "message": "The handoff was successfully initiated. Waiting for confirmation.",
    }


def test_handoff_tool_is_absent_when_unconfigured() -> None:
    tools = build_agent_tools(runtime_context(), None, uuid4())  # type: ignore[arg-type]
    assert [tools[0]._info.name, tools[1].id] == ["calculator", "end_call"]  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_capability_timeout_returns_only_safe_semantics() -> None:
    class Backend:
        async def invoke_capability(self, call_id, request):
            raise TimeoutError

    context = SimpleNamespace(function_call=SimpleNamespace(call_id="tool-call"))
    definition = runtime_action(
        "reservation.submit_request",
        announcement="I will submit your reservation request now.",
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

    definition = runtime_action(
        "reservation.check_availability",
        announcement="I will check availability.",
    )
    tool = capability_tool(  # type: ignore[arg-type]
        definition,
        Backend(),
        uuid4(),
        lambda **values: recorded.append(values),
    )
    result = await tool._func(  # type: ignore[attr-defined]
        SimpleNamespace(function_call=SimpleNamespace(call_id="tool-call")),
        {},
    )
    assert result == {"status": "available"}
    assert len(recorded) == 1
    assert recorded[0]["name"] == "reservation.check_availability"
    assert recorded[0]["version"] == "execution"
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

    definition = runtime_action(
        "reservation.create_request",
        announcement="I will submit your reservation request.",
    )
    tool = capability_tool(
        definition,
        Backend(),
        uuid4(),
        lambda **values: recorded.append(values),
    )

    result = await tool._func(  # type: ignore[attr-defined]
        SimpleNamespace(function_call=SimpleNamespace(call_id="tool-call")),
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
async def test_provider_factory_uses_openai_client_for_foundry_v1_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    original_init = openai.LLM.__init__

    def capture_init(self: object, **kwargs: object) -> None:
        captured.update(kwargs)
        original_init(self, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(openai.LLM, "__init__", capture_init)
    runtime = runtime_settings()
    llm = runtime["llm"]
    assert isinstance(llm, dict)
    connection = llm["connection_config"]
    assert isinstance(connection, dict)
    connection["endpoint"] = (
        "https://ct-val.services.ai.azure.com/api/projects/CloudSystems-ai/openai/v1"
    )
    session = create_agent_session(
        settings(),
        runtime,
        "voice-agent-prompt:test",
        secrets={"llm": "azure-key", "stt": "eleven-key", "tts": "eleven-key"},
    )
    try:
        assert captured["base_url"] == (
            "https://ct-val.services.ai.azure.com/api/projects/CloudSystems-ai/openai/v1"
        )
        assert captured["model"] == "model-a"
        assert captured["api_key"] == "azure-key"
    finally:
        await session.stt.aclose()
        await session.llm.aclose()
        await session.tts.aclose()


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
        settings(),
        runtime_settings(
            llm={
                "provider": "azure_openai",
                "model": "model-a",
                "max_completion_tokens": 777,
                "temperature": 0,
            },
            response_scheduling={
                "preemptive_generation": False,
                "preemptive_tts": False,
            },
        ),
        "voice-agent-prompt:test",
        secrets={"llm": "azure-key", "stt": "eleven-key", "tts": "eleven-key"},
    )
    try:
        assert isinstance(session.stt, elevenlabs.STT)
        provider_stt = session.stt
        assert isinstance(session.llm, openai.LLM)
        assert isinstance(session.tts, elevenlabs.TTS)
        assert provider_stt._opts.model_id == "scribe_v2_realtime"
        assert not is_given(provider_stt._opts.keyterms)
        assert str(provider_stt._opts.language_code) == "sk"
        assert provider_stt._opts.server_vad["vad_silence_threshold_secs"] == 0.35
        assert provider_stt._opts.server_vad["min_silence_duration_ms"] == 350
        assert session.vad is not None
        assert session._opts.user_away_timeout == 10.0
        assert session.vad.model == "silero"
        assert session.vad._opts.min_speech_duration == 0.05
        assert session.vad._opts.min_silence_duration == 0.25
        assert session.vad._opts.activation_threshold == 0.5
        assert session.turn_detection == "stt"
        assert session._opts.turn_handling["endpointing"]["min_delay"] == 0.1
        assert session._opts.turn_handling["endpointing"]["max_delay"] == 0.7
        assert session._opts.turn_handling["preemptive_generation"]["enabled"] is False
        assert (
            session._opts.turn_handling["preemptive_generation"]["preemptive_tts"]
            is False
        )
        assert session.llm._opts.temperature == 0
        assert session.llm._opts.max_completion_tokens == 777
        assert azure["model"] == "model-a"
        assert azure["azure_deployment"] == "deployment"
        assert azure["azure_endpoint"] == "https://test.openai.azure.com"
        assert azure["api_version"] == "2025-01-01-preview"
        assert azure["api_key"] == "azure-key"
        assert azure["prompt_cache_key"] == "voice-agent-prompt:test"
        assert azure["max_completion_tokens"] == 777
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


@pytest.mark.asyncio
async def test_provider_factory_enables_manual_scribe_commit_without_changing_turn_mode() -> (
    None
):
    payload = runtime_settings()
    payload["stt"]["commit"]["strategy"] = "local_vad"  # type: ignore[index]
    session = create_agent_session(
        settings(),
        payload,
        "voice-agent-prompt:test",
        secrets={"llm": "azure-key", "stt": "eleven-key", "tts": "eleven-key"},
    )
    try:
        assert isinstance(session.stt, LocalVadCommitSTT)
        provider_stt = session.stt.wrapped_stt
        assert isinstance(provider_stt, elevenlabs.STT)
        assert not is_given(provider_stt._opts.server_vad)
        assert session.turn_detection == "stt"
        assert isinstance(session.llm, openai.LLM)
        assert isinstance(session.tts, elevenlabs.TTS)
    finally:
        await session.stt.aclose()
        await session.llm.aclose()
        await session.tts.aclose()


@pytest.mark.asyncio
async def test_provider_factory_uses_native_soniox_endpoint_without_vad_commit_wrapper() -> (
    None
):
    payload = runtime_settings(stt={"provider": "soniox", "model": "stt-rt-v5"})
    payload["stt"]["deployment_config"] = {"model": "stt-rt-v5"}  # type: ignore[index]
    payload["stt"]["commit"] = {"strategy": "stt"}  # type: ignore[index]
    session = create_agent_session(
        settings(),
        payload,
        "voice-agent-prompt:test",
        secrets={"llm": "azure-key", "stt": "soniox-key", "tts": "eleven-key"},
    )
    try:
        assert isinstance(session.stt, soniox.STT)
        assert session.vad is not None
        assert session.turn_detection == "stt"
    finally:
        await session.stt.aclose()
        await session.llm.aclose()
        await session.tts.aclose()


@pytest.mark.asyncio
async def test_provider_factory_passes_tenant_keyterms_to_elevenlabs() -> None:
    session = create_agent_session(
        settings(),
        runtime_settings(
            stt={
                "provider": "elevenlabs",
                "model": "scribe_v2_realtime",
                "keyterms": ["Kováčska", "Penzión Grand"],
                "server_vad": {
                    "silence_threshold_seconds": 0.35,
                    "activity_threshold": 0.35,
                    "min_speech_ms": 100,
                    "min_silence_ms": 350,
                },
            }
        ),
        "voice-agent-prompt:test",
        secrets={"llm": "azure-key", "stt": "eleven-key", "tts": "eleven-key"},
    )
    try:
        assert session.stt._opts.keyterms == ["Kováčska", "Penzión Grand"]
    finally:
        await session.stt.aclose()
        await session.llm.aclose()
        await session.tts.aclose()


@pytest.mark.asyncio
async def test_soniox_factory_uses_slovak_hints_and_keeps_scheduling_independent() -> (
    None
):
    runtime = runtime_settings(
        response_scheduling={
            "preemptive_generation": True,
            "preemptive_tts": False,
        }
    )
    runtime["stt"]["provider_kind"] = "soniox"  # type: ignore[index]
    runtime["stt"]["connection_config"] = {"region": "eu"}  # type: ignore[index]
    runtime["stt"]["deployment_config"] = {  # type: ignore[index]
        "model": "stt-rt-v5",
        "max_endpoint_delay_ms": 700,
        "endpoint_sensitivity": 0.2,
        "endpoint_latency_adjustment_level": 2,
    }
    session = create_agent_session(
        settings(),
        runtime,
        "voice-agent-prompt:test",
        secrets={"llm": "azure-key", "stt": "soniox-key", "tts": "eleven-key"},
    )
    try:
        assert isinstance(session.stt, soniox.STT)
        assert (
            session.stt._base_url == "wss://stt-rt.eu.soniox.com/transcribe-websocket"
        )
        assert session.stt._params.model == "stt-rt-v5"
        assert session.stt._params.language_hints == ["sk"]
        assert session.stt._params.max_endpoint_delay_ms == 700
        assert session.stt._params.endpoint_sensitivity == 0.2
        assert session.stt._params.endpoint_latency_adjustment_level == 2
        assert session.stt._api_key == "soniox-key"
        assert isinstance(session.llm, openai.LLM)
        assert isinstance(session.tts, elevenlabs.TTS)
        assert session._opts.turn_handling["preemptive_generation"]["enabled"] is True
        assert (
            session._opts.turn_handling["preemptive_generation"]["preemptive_tts"]
            is False
        )
    finally:
        await session.stt.aclose()
        await session.llm.aclose()
        await session.tts.aclose()


@pytest.mark.asyncio
async def test_soniox_local_vad_commit_wrapper_preserves_preflight_events() -> None:
    runtime = runtime_settings(
        response_scheduling={
            "preemptive_generation": True,
            "preemptive_tts": True,
        }
    )
    runtime["stt"]["provider_kind"] = "soniox"  # type: ignore[index]
    runtime["stt"]["connection_config"] = {"region": "eu"}  # type: ignore[index]
    runtime["stt"]["commit"]["strategy"] = "local_vad"  # type: ignore[index]
    runtime["stt"]["deployment_config"] = {"model": "stt-rt-v5"}  # type: ignore[index]
    session = create_agent_session(
        settings(),
        runtime,
        "voice-agent-prompt:test",
        secrets={"llm": "azure-key", "stt": "soniox-key", "tts": "eleven-key"},
    )
    try:
        assert isinstance(session.stt, LocalVadCommitSTT)
        assert isinstance(session.stt.wrapped_stt, soniox.STT)
        assert session.stt.wrapped_stt._params.max_endpoint_delay_ms == 2000
        assert session.stt.wrapped_stt._params.endpoint_sensitivity is None
        assert session.stt.wrapped_stt._params.endpoint_latency_adjustment_level is None
        assert session._opts.turn_handling["preemptive_generation"]["enabled"] is True
        assert (
            session._opts.turn_handling["preemptive_generation"]["preemptive_tts"]
            is True
        )
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
    session = create_agent_session(
        settings(),
        runtime,
        "voice-agent-prompt:test",
        secrets={"llm": "azure-key", "stt": "eleven-key", "tts": "eleven-key"},
    )
    try:
        provider_stt = session.stt
        assert isinstance(provider_stt, elevenlabs.STT)
        assert provider_stt._opts.server_vad["vad_silence_threshold_secs"] == 0.25
        assert provider_stt._opts.server_vad["min_silence_duration_ms"] == 250
        assert session.tts._opts.word_tokenizer._config.min_sentence_len == 12
    finally:
        await session.stt.aclose()
        await session.llm.aclose()
        await session.tts.aclose()


@pytest.mark.asyncio
async def test_phrase_tokenizer_settings_reach_voice_execution_tts() -> None:
    runtime = runtime_settings(
        tts={"strategy": "phrase", "min_phrase_chars": 10},
    )
    session = create_agent_session(
        settings(),
        runtime,
        "voice-agent-prompt:test",
        secrets={"llm": "azure-key", "stt": "eleven-key", "tts": "eleven-key"},
    )
    try:
        assert session.tts._opts.word_tokenizer.tokenize("Dobrý deň,") == ["Dobrý deň,"]
        assert session.tts._opts.auto_mode is True
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
                "max_completion_tokens": 256,
                "temperature": 0,
            }
        ),
        "voice-agent-prompt:test",
        secrets={"llm": "azure-key", "stt": "eleven-key", "tts": "eleven-key"},
    )
    try:
        assert session.llm._opts.model == "model-b"
    finally:
        await session.stt.aclose()
        await session.llm.aclose()
        await session.tts.aclose()


@pytest.mark.asyncio
async def test_provider_factory_uses_direct_openai_llm_deployment() -> None:
    runtime = runtime_settings()
    llm = runtime["llm"]
    assert isinstance(llm, dict)
    llm["provider_kind"] = "openai"
    llm["deployment_config"] = {"model": "gpt-4.1", "service_tier": "fast"}
    llm["connection_config"] = {}
    session = create_agent_session(
        settings(),
        runtime,
        "voice-agent-prompt:test",
        secrets={
            "llm": "openai-key",
            "stt": "eleven-key",
            "tts": "eleven-key",
        },
    )
    try:
        assert session.llm._opts.model == "gpt-4.1"
        assert session.llm._opts.service_tier == "fast"
        assert session.llm._client.api_key == "openai-key"
    finally:
        await session.stt.aclose()
        await session.llm.aclose()
        await session.tts.aclose()


@pytest.mark.asyncio
async def test_provider_factory_applies_azure_service_tier() -> None:
    runtime = runtime_settings()
    llm = runtime["llm"]
    assert isinstance(llm, dict)
    llm["deployment_config"]["service_tier"] = "priority"
    session = create_agent_session(
        settings(),
        runtime,
        "voice-agent-prompt:test",
        secrets={"llm": "azure-key", "stt": "eleven-key", "tts": "eleven-key"},
    )
    try:
        assert session.llm._opts.service_tier == "priority"
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
async def test_greeting_uses_configured_tts_and_chat_history() -> None:
    calls: list[tuple[str, object]] = []
    speech = asyncio.get_running_loop().create_future()

    class FakeSession:
        def __init__(self) -> None:
            self.tts = object()

        async def say(
            self, text: str, *, add_to_chat_ctx: bool, allow_interruptions: bool
        ):
            calls.append(("say", (text, add_to_chat_ctx, allow_interruptions)))
            return FakeSpeechHandle(speech)

        async def generate_reply(self, **kwargs: object):
            calls.append(("generate_reply", kwargs))

    task = asyncio.create_task(send_greeting(FakeSession(), "Добрый день"))  # type: ignore[arg-type]
    await asyncio.sleep(0)
    assert not task.done()
    speech.set_result(None)
    await task

    assert calls == [("say", ("Добрый день", True, False))]


@pytest.mark.asyncio
async def test_realtime_greeting_falls_back_to_generation() -> None:
    calls: list[tuple[str, object]] = []
    speech = asyncio.get_running_loop().create_future()

    class FakeSession:
        tts = None

        async def generate_reply(self, **kwargs: object):
            calls.append(("generate_reply", kwargs))
            return FakeSpeechHandle(speech)

        async def say(
            self, text: str, *, add_to_chat_ctx: bool, allow_interruptions: bool
        ):
            raise AssertionError("realtime greeting should use generation fallback")

    task = asyncio.create_task(send_greeting(FakeSession(), "Добрый день"))  # type: ignore[arg-type]
    await asyncio.sleep(0)
    assert not task.done()
    speech.set_result(None)
    await task

    assert calls == [
        (
            "generate_reply",
            {
                "instructions": "say Добрый день",
                "input_modality": "audio",
                "allow_interruptions": False,
            },
        )
    ]


@pytest.mark.asyncio
async def test_participant_timeout_fails_once(monkeypatch: pytest.MonkeyPatch) -> None:
    context = runtime_context()
    call_id = uuid4()

    class FakeBackend:
        def __init__(self) -> None:
            self.failed: list[str] = []
            self.activated = False

        async def runtime_context(self, call_id):
            return context

        async def runtime_secret(self, execution_id, slot):
            return f"{slot}-secret"

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
        tts = None

        def on(self, event, callback):
            return callback

        async def start(self, agent, *, room, record) -> None:
            return None

        async def generate_reply(self, *, instructions, input_modality) -> None:
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
        job = SimpleNamespace(metadata=f'{{"call_session_id":"{call_id}"}}')
        room = SimpleNamespace(name="room")

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
    claimed_call_id = uuid4()
    order: list[str] = []
    inactivity_instructions: list[str] = []
    callbacks: dict[str, object] = {}

    class FakeBackend:
        async def claim_inbound_sip(self, request):
            order.append("claim")
            return InboundSipClaimResponse(
                call_session_id=claimed_call_id, created=True
            )

        async def runtime_context(self, call_id):
            order.append("runtime-context")
            assert call_id == claimed_call_id
            return context

        async def runtime_secret(self, execution_id, slot):
            return f"{slot}-secret"

        async def observe(self, call_id, observation_type: str, **kwargs) -> None:
            if observation_type == "session_started":
                order.append("call.started")

        async def activate(self, call_id) -> None:
            order.append("activate")

        async def start_recording(self, call_id) -> None:
            order.append("recording-start")
            callbacks["close"](
                SimpleNamespace(reason=agents.CloseReason.TASK_COMPLETED)
            )  # type: ignore[operator]

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
            self.tts = object()

        def on(self, event, callback):
            self.callbacks[event] = callback
            callbacks[event] = callback

        def off(self, event, callback):
            return None

        async def start(self, agent, *, room, record) -> None:
            self.record = record
            order.append("session-start")
            self.callbacks["user_state_changed"](SimpleNamespace(new_state="away"))  # type: ignore[operator]

        async def generate_reply(self, *, instructions, input_modality="text") -> None:
            inactivity_instructions.append(instructions)

        async def say(
            self, text: str, *, add_to_chat_ctx: bool, allow_interruptions: bool
        ):
            assert allow_interruptions is False
            order.append("intro-start")

            async def playout() -> None:
                await asyncio.sleep(0)
                order.append("intro-playout-complete")

            class Speech:
                async def wait_for_playout(self) -> None:
                    await asyncio.create_task(playout())

            return Speech()

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

    room_callbacks: dict[str, object] = {}

    class Room:
        name = "sip-call-run-job"

        def on(self, event, callback) -> None:
            room_callbacks[event] = callback

        def off(self, event, callback) -> None:
            assert room_callbacks[event] is callback
            del room_callbacks[event]

    class Context:
        job = SimpleNamespace(metadata="")
        room = Room()

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
    assert order.index("session-start") < order.index("call.started")
    assert order.index("call.started") < order.index("activate")
    assert order.index("activate") < order.index("intro-start")
    assert order.index("intro-playout-complete") < order.index("recording-start")
    assert order.index("recording-start") < order.index("complete")
    assert order[-1] == "complete"
    assert len(sessions) == 1
    assert len(inactivity_instructions) == 1
    assert "caller is still present" in inactivity_instructions[0]
    assert "Ste tam?" not in inactivity_instructions[0]
    assert sessions[0].record == {
        "audio": False,
        "traces": False,
        "logs": False,
        "transcript": False,
    }
    assert not room_callbacks


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("user_speaks", "handoff_starts", "caller_disconnects", "terminal_state"),
    [
        (True, False, False, None),
        (False, False, False, None),
        (False, True, False, None),
        (False, False, True, None),
        (False, True, False, "timed_out"),
        (False, True, False, "failed"),
        (False, True, False, "canceled"),
        (False, True, False, "stale"),
        (False, True, True, "failed_caller_disconnect"),
        (False, True, True, "dialing_caller_disconnect"),
    ],
)
async def test_inactivity_nudge_does_not_extend_deadline_and_activity_cancels_it(
    monkeypatch: pytest.MonkeyPatch,
    user_speaks: bool,
    handoff_starts: bool,
    caller_disconnects: bool,
    terminal_state: str | None,
) -> None:
    context = runtime_context()
    call_id = uuid4()
    deadline = asyncio.Event()
    resume_deadline = asyncio.Event()
    resume_started = asyncio.Event()
    timer_started = asyncio.Event()
    timer_cancelled = asyncio.Event()
    nudge_started = asyncio.Event()
    nudge_release = asyncio.Event()
    call_finalized = asyncio.Event()
    deleted_rooms: list[str] = []
    ringback_events: list[tuple[str, object]] = []
    permissions: list[dict[str, object]] = []
    original_sleep = asyncio.sleep

    async def controlled_sleep(delay: float) -> None:
        if delay == 10.0:
            resume_started.set()
            await resume_deadline.wait()
            return
        assert delay == 15.0
        timer_started.set()
        try:
            await deadline.wait()
        except asyncio.CancelledError:
            timer_cancelled.set()
            raise

    monkeypatch.setattr("voice_agent.main.asyncio.sleep", controlled_sleep)

    class Backend:
        async def runtime_context(self, call_id):
            return context

        async def runtime_secret(self, execution_id, slot):
            return f"{slot}-secret"

        async def observe(self, call_id, observation_type: str, **kwargs) -> None:
            return None

        async def activate(self, call_id) -> None:
            return None

        async def start_recording(self, call_id) -> None:
            return None

        async def complete(self, call_id, conversation_status: str) -> None:
            call_finalized.set()

        async def fail(self, call_id, reason: str, conversation_status: str) -> None:
            raise AssertionError(f"call unexpectedly failed: {reason}")

        async def aclose(self) -> None:
            return None

    class Handoff:
        def __init__(self, backend, call_id, timeout) -> None:
            self.state: HandoffState | None = None
            self.listener = None
            self.attempt_id = uuid4()
            self.destination = "reception"

        @property
        def active(self) -> bool:
            return self.state in {HandoffState.DIALING, HandoffState.ANSWERED}

        @property
        def completed(self) -> bool:
            return self.state is HandoffState.COMPLETED

        def set_state_listener(self, listener) -> None:
            self.listener = listener

        def set_caller_identity(self, identity: str) -> None:
            return None

        def bridge_peer_disconnected(self, identity: str) -> bool:
            return False

        def start(self) -> None:
            self.state = HandoffState.DIALING
            self.listener(self.state, "started")

        def complete(self) -> None:
            self.state = HandoffState.COMPLETED
            self.listener(self.state, "complete")

        def answer(self) -> None:
            self.state = HandoffState.ANSWERED
            self.listener(self.state, "answer")

        def time_out(self) -> None:
            self.state = HandoffState.TIMED_OUT
            self.listener(self.state, "time_out")

        def fail(self) -> None:
            self.state = HandoffState.FAILED
            self.listener(self.state, "fail")

        async def cancel(self, reason: str) -> bool:
            self.state = HandoffState.CANCELED
            self.listener(self.state, reason)
            return True

        async def close(self, *, cancel: bool = True) -> None:
            return None

    handoff = Handoff(None, call_id, 25.0)

    class Session:
        def __init__(self) -> None:
            self.callbacks: dict[str, object] = {}
            self.tts = object()
            self.user_state = "listening"
            self.input_states: list[bool] = []
            self.output_states: list[bool] = []
            self.interruptions: list[bool] = []
            self.recovery_contexts: list[list[object]] = []
            self.recovery_replies = 0
            self.current_agent = SimpleNamespace(
                chat_ctx=agents.llm.ChatContext(), update_chat_ctx=self.update_chat_ctx
            )
            self.input = SimpleNamespace(set_audio_enabled=self.input_states.append)
            self.output = SimpleNamespace(
                audio=None,
                set_audio_enabled=self.output_states.append,
                set_transcription_enabled=lambda enabled: None,
            )

        def on(self, event, callback):
            self.callbacks[event] = callback

        def off(self, event, callback):
            return None

        def interrupt(self, *, force: bool = False):
            self.interruptions.append(force)

        async def start(self, agent, *, room, record) -> None:
            return None

        async def update_chat_ctx(self, chat_ctx) -> None:
            self.current_agent.chat_ctx = chat_ctx
            self.recovery_contexts.append(chat_ctx.messages())

        def generate_reply(self, *, instructions=None, input_modality="text"):
            if instructions is None:
                self.recovery_replies += 1
                return None

            async def nudge() -> None:
                assert "caller is still present" in instructions
                nudge_started.set()
                await nudge_release.wait()

            return asyncio.create_task(nudge())

        async def say(
            self, text: str, *, add_to_chat_ctx: bool, allow_interruptions: bool
        ):
            self.user_state = "away"
            self.callbacks["user_state_changed"](SimpleNamespace(new_state="away"))  # type: ignore[operator]
            await timer_started.wait()
            await nudge_started.wait()
            if user_speaks:
                self.callbacks["user_state_changed"](
                    SimpleNamespace(new_state="speaking")
                )  # type: ignore[operator]
                nudge_release.set()
                await original_sleep(0)
                assert not deleted_rooms
                self.callbacks["close"](
                    SimpleNamespace(reason=agents.CloseReason.USER_INITIATED)
                )  # type: ignore[operator]
            elif handoff_starts:
                handoff.start()
                assert self.input_states[-1] is False
                assert self.output_states[-1] is False
                assert self.interruptions == [True]
                assert ringback_events[-1] == ("start", handoff.attempt_id)
                assert permissions[-1]["allow_all_participants"] is False
                assert {
                    item.participant_identity
                    for item in permissions[-1]["participant_permissions"]
                } == {"caller", "egress"}
                deadline.set()
                await original_sleep(0)
                assert not deleted_rooms
                nudge_started.clear()
                self.callbacks["user_state_changed"](SimpleNamespace(new_state="away"))  # type: ignore[operator]
                await original_sleep(0)
                assert not nudge_started.is_set()
                if terminal_state == "dialing_caller_disconnect":
                    room_callbacks["participant_disconnected"](
                        SimpleNamespace(identity="caller")
                    )
                    await original_sleep(0)
                    assert self.recovery_replies == 0
                elif terminal_state == "failed_caller_disconnect":
                    handoff.fail()
                    room_callbacks["participant_disconnected"](
                        SimpleNamespace(identity="caller")
                    )
                    await original_sleep(0)
                    assert self.recovery_replies == 0
                elif terminal_state == "stale":
                    handoff.fail()
                    handoff.attempt_id = uuid4()
                    handoff.start()
                    await original_sleep(0)
                    assert self.recovery_replies == 0
                    assert self.recovery_contexts == []
                elif terminal_state is not None:
                    deadline.clear()
                    if terminal_state == "timed_out":
                        handoff.time_out()
                    elif terminal_state == "failed":
                        handoff.fail()
                    else:
                        await handoff.cancel("returning_cancel")
                    assert self.input_states[-1] is True
                    assert self.output_states[-1] is True
                    assert ringback_events[-1] == (
                        "stop",
                        {
                            "timed_out": "time_out",
                            "failed": "fail",
                            "canceled": "returning_cancel",
                        }[terminal_state],
                    )
                    await asyncio.wait_for(resume_started.wait(), 1)
                    await original_sleep(0)
                    assert not nudge_started.is_set()
                    assert self.recovery_replies == 1
                    assert len(self.recovery_contexts) == 1
                    result_text = self.recovery_contexts[0][-1].raw_text_content
                    assert f"status={terminal_state}" in result_text
                    assert "destination=reception" in result_text
                    assert "Handoff is no longer in progress" in result_text
                    assert all(
                        message.role != "user" for message in self.recovery_contexts[0]
                    )
                    resume_deadline.set()
                    await asyncio.wait_for(nudge_started.wait(), 1)
                else:
                    handoff.answer()
                    assert self.output_states[-1] is False
                    assert ringback_events[-1] == ("stop", "answer")
                    handoff.complete()
                    assert self.output_states[-1] is False
                    assert ringback_events[-1] == ("stop", "complete")
                self.callbacks["close"](
                    SimpleNamespace(reason=agents.CloseReason.USER_INITIATED)
                )  # type: ignore[operator]
            elif caller_disconnects:
                room_callbacks["participant_disconnected"](
                    SimpleNamespace(identity="caller")
                )  # type: ignore[operator]
                nudge_release.set()
                await original_sleep(0)
                assert not deleted_rooms
            else:
                # The nudge remains in progress when the 15-second timer expires.
                deadline.set()
                await original_sleep(0)

            async def playout() -> None:
                await original_sleep(0)

            return asyncio.create_task(playout())

        async def aclose(self) -> None:
            return None

    session = Session()

    room_callbacks: dict[str, object] = {}

    class Room:
        name = "inactivity-test"
        local_participant = SimpleNamespace(
            set_track_subscription_permissions=lambda **kwargs: permissions.append(
                kwargs
            )
        )

        def __init__(self) -> None:
            self.remote_participants = {
                "egress": SimpleNamespace(
                    identity="egress",
                    kind=rtc.ParticipantKind.PARTICIPANT_KIND_EGRESS,
                ),
                "owner": SimpleNamespace(
                    identity="owner",
                    kind=rtc.ParticipantKind.PARTICIPANT_KIND_SIP,
                ),
            }

        def on(self, event, callback) -> None:
            room_callbacks[event] = callback

        def off(self, event, callback) -> None:
            assert room_callbacks[event] is callback
            del room_callbacks[event]

    class Context:
        job = SimpleNamespace(metadata=f'{{"call_session_id":"{call_id}"}}')
        room = Room()

        def add_shutdown_callback(self, callback) -> None:
            return None

        async def wait_for_participant(self, **kwargs):
            return SimpleNamespace(
                kind=(
                    rtc.ParticipantKind.PARTICIPANT_KIND_SIP
                    if caller_disconnects
                    else rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD
                ),
                identity="caller",
                attributes={},
            )

        async def delete_room(self) -> None:
            deleted_rooms.append(self.room.name)
            session.callbacks["close"](
                SimpleNamespace(reason=agents.CloseReason.PARTICIPANT_DISCONNECTED)
            )  # type: ignore[operator]

    monkeypatch.setattr("voice_agent.main.BackendClient", lambda _: Backend())
    monkeypatch.setattr("voice_agent.main.create_agent_session", lambda *_: session)
    monkeypatch.setattr(
        "voice_agent.main.RingbackPlayer",
        lambda *args: SimpleNamespace(
            caller_identity="caller",
            start=lambda attempt_id: ringback_events.append(("start", attempt_id)),
            stop=lambda reason: ringback_events.append(("stop", reason)),
            aclose=lambda: original_sleep(0),
        ),
    )
    monkeypatch.setattr(
        "voice_agent.main.HandoffController", lambda *args, **kwargs: handoff
    )
    await run_job(Context(), settings())  # type: ignore[arg-type]

    assert deleted_rooms == (
        ["inactivity-test"]
        if not user_speaks and not handoff_starts and not caller_disconnects
        else []
    )
    if caller_disconnects:
        assert timer_cancelled.is_set()
        assert call_finalized.is_set()
        assert not room_callbacks


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "first_peer", "close_first"),
    [
        (HandoffState.ANSWERED, "caller", False),
        (HandoffState.ANSWERED, "destination", False),
        (HandoffState.COMPLETED, "caller", False),
        (HandoffState.COMPLETED, "destination", False),
        (HandoffState.ANSWERED, "caller", True),
    ],
)
async def test_bridge_disconnect_deletes_room_and_finalizes_once(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    state: HandoffState,
    first_peer: str,
    close_first: bool,
) -> None:
    caplog.set_level("INFO")
    context = runtime_context().model_copy(
        update={
            "handoff": [
                {"destination_key": "reception", "description": "Reception requests"}
            ]
        }
    )
    call_id = uuid4()
    controllers: list[object] = []
    deleted_rooms: list[str] = []
    sessions: list[object] = []
    shutdowns: list[bool] = []

    class Backend:
        def __init__(self) -> None:
            self.observations: list[tuple[str, str]] = []

        async def runtime_context(self, call_id):
            return context

        async def runtime_secret(self, execution_id, slot):
            return f"{slot}-secret"

        async def observe(
            self,
            call_id,
            observation_type: str,
            *,
            conversation_status: str = "complete",
            handoff_attempt_id=None,
        ) -> None:
            self.observations.append((observation_type, conversation_status))

        async def activate(self, call_id) -> None:
            return None

        async def start_recording(self, call_id) -> None:
            controller = controllers[0]
            for identity in ("egress", "agent", "unrelated", f"handoff-{uuid4()}"):
                assert not controller.bridge_peer_disconnected(identity)
            assert not deleted_rooms
            peers = (
                ("caller", "handoff-participant")
                if first_peer == "caller"
                else ("handoff-participant", "caller")
            )
            if close_first:
                sessions[0].callbacks["close"](  # type: ignore[attr-defined]
                    SimpleNamespace(reason=agents.CloseReason.PARTICIPANT_DISCONNECTED)
                )
            for identity in peers:
                if identity == "caller":
                    job.room.emit("participant_disconnected", identity)
                else:
                    assert controller.bridge_peer_disconnected(identity)

        async def complete(self, call_id, conversation_status: str) -> None:
            self.observations.append(("complete", conversation_status))

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
        tts = None

        def __init__(self) -> None:
            self.callbacks: dict[str, object] = {}

        def on(self, event, callback):
            self.callbacks[event] = callback

        def off(self, event, callback):
            return None

        async def start(self, agent, *, room, record) -> None:
            return None

        async def generate_reply(
            self, *, instructions, input_modality, allow_interruptions=True
        ):
            speech = asyncio.get_running_loop().create_future()
            speech.set_result(None)
            return FakeSpeechHandle(speech)

        async def say(self, text, *, add_to_chat_ctx, allow_interruptions):
            speech = asyncio.get_running_loop().create_future()
            speech.set_result(None)
            return FakeSpeechHandle(speech)

        async def aclose(self) -> None:
            return None

        def shutdown(self, *, drain: bool) -> None:
            assert drain is False
            shutdowns.append(drain)
            self.callbacks["close"](
                SimpleNamespace(reason=agents.CloseReason.USER_INITIATED)
            )

    class Room:
        name = "room"

        def __init__(self) -> None:
            self.remote_participants = {
                "caller": object(),
                "handoff-participant": object(),
            }
            self.callbacks: dict[str, object] = {}

        def on(self, event, callback) -> None:
            self.callbacks[event] = callback

        def off(self, event, callback) -> None:
            self.callbacks.pop(event, None)

        def emit(self, event, identity: str) -> None:
            self.remote_participants.pop(identity, None)
            callback = self.callbacks.get(event)
            if callback is not None:
                callback(SimpleNamespace(identity=identity))

    class Context:
        job = SimpleNamespace(metadata=f'{{"call_session_id":"{call_id}"}}')

        def __init__(self) -> None:
            self.room = Room()

        def add_shutdown_callback(self, callback) -> None:
            return None

        async def wait_for_participant(self, **kwargs):
            return SimpleNamespace(
                kind=rtc.ParticipantKind.PARTICIPANT_KIND_SIP,
                identity="caller",
                attributes={},
            )

        async def delete_room(self) -> None:
            deleted_rooms.append(self.room.name)
            self.room.remote_participants.clear()
            sessions[0].callbacks["close"](  # type: ignore[attr-defined]
                SimpleNamespace(reason=agents.CloseReason.PARTICIPANT_DISCONNECTED)
            )
            sessions[0].callbacks["close"](  # type: ignore[attr-defined]
                SimpleNamespace(reason=agents.CloseReason.PARTICIPANT_DISCONNECTED)
            )

    backend = Backend()
    monkeypatch.setattr("voice_agent.main.BackendClient", lambda _: backend)
    monkeypatch.setattr("voice_agent.main.ConversationPersistence", Persistence)
    monkeypatch.setattr(
        "voice_agent.main.create_agent_session",
        lambda *_: sessions.append(Session()) or sessions[0],
    )

    def tools(
        runtime,
        client,
        call_id,
        controller,
        capability_recorder=None,
        recent_transcript=None,
    ):
        controllers.append(controller)
        controller._attempt = HandoffAttempt(uuid4(), "handoff-participant", state)
        return []

    monkeypatch.setattr("voice_agent.main.build_agent_tools", tools)

    job = Context()
    await run_job(job, settings())  # type: ignore[arg-type]

    assert backend.observations == [
        ("session_started", "complete"),
        ("complete", "complete"),
    ]
    assert deleted_rooms == ["room"]
    assert shutdowns == [False]
    assert job.room.remote_participants == {}
    bridge_logs = [
        record for record in caplog.records if record.msg == "handoff_bridge_terminated"
    ]
    assert len(bridge_logs) == 1
    assert bridge_logs[0].call_id == str(call_id)
    assert bridge_logs[0].attempt_id == str(controllers[0].attempt_id)
    assert bridge_logs[0].disconnected_participant == (
        "caller" if first_peer == "caller" else "handoff-participant"
    )
    assert bridge_logs[0].disconnected_role == first_peer
    assert bridge_logs[0].handoff_state == state.value


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
    call_id = uuid4()

    class FakeBackend:
        def __init__(self) -> None:
            self.completed: list[str] = []
            self.failed: list[str] = []

        async def runtime_context(self, call_id):
            return context

        async def runtime_secret(self, execution_id, slot):
            return f"{slot}-secret"

        async def observe(self, call_id, observation_type: str) -> None:
            return None

        async def activate(self, call_id) -> None:
            return None

        async def start_recording(self, call_id) -> None:
            return None

        async def complete(self, call_id, conversation_status: str) -> None:
            self.completed.append(conversation_status)

        async def fail(self, call_id, reason: str, conversation_status: str) -> None:
            self.failed.append(reason)

        async def aclose(self) -> None:
            return None

    class FakeSession:
        tts = None

        def __init__(self) -> None:
            self.callbacks: dict[str, object] = {}
            self.greeted = asyncio.Event()
            self.playout: asyncio.Future[None] = (
                asyncio.get_running_loop().create_future()
            )

        def on(self, event, callback):
            self.callbacks[event] = callback

        def off(self, event, callback):
            return None

        async def start(self, agent, *, room, record) -> None:
            return None

        async def generate_reply(
            self, *, instructions, input_modality, allow_interruptions=True
        ):
            self.greeted.set()
            return FakeSpeechHandle(self.playout)

        async def say(
            self, text: str, *, add_to_chat_ctx: bool, allow_interruptions: bool
        ):
            self.greeted.set()
            return FakeSpeechHandle(self.playout)

        async def aclose(self) -> None:
            return None

    backend = FakeBackend()
    session = FakeSession()
    monkeypatch.setattr("voice_agent.main.BackendClient", lambda _: backend)
    monkeypatch.setattr("voice_agent.main.create_agent_session", lambda *_: session)

    class Context:
        job = SimpleNamespace(metadata=f'{{"call_session_id":"{call_id}"}}')
        room = SimpleNamespace(name="room")
        shutdown = None

        def add_shutdown_callback(self, callback) -> None:
            self.shutdown = callback

        async def wait_for_participant(self, **kwargs):
            return SimpleNamespace(
                kind=rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD,
                identity="caller",
                attributes={},
            )

    job = Context()
    task = asyncio.create_task(run_job(job, settings()))
    await session.greeted.wait()
    callback = session.callbacks["close"]
    callback(SimpleNamespace(reason=close_reason))
    assert not task.done()
    session.playout.set_result(None)
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
