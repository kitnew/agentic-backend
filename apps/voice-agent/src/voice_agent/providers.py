from typing import Any

import httpx
from contracts import EffectiveVoiceRuntime
from contracts.voice_runtime import model_supports_reasoning
from livekit import agents
from livekit.agents import inference, tokenize
from livekit.agents import stt as livekit_stt
from livekit.agents.types import NOT_GIVEN, NotGivenOr
from livekit.agents.voice.agent_session import SessionConnectOptions
from livekit.plugins import elevenlabs, openai
from livekit.plugins.elevenlabs.stt import VADOptions
from livekit.plugins.openai import realtime

from voice_agent.observability import VoiceMetrics
from voice_agent.settings import VoiceAgentSettings
from voice_agent.stt_endpointing import LocalVadCommitController, LocalVadCommitSTT


def provider_languages(locale: str) -> tuple[str, str]:
    language = locale.partition("-")[0].lower()
    if language != "sk":
        raise ValueError("the voice deployment supports Slovak runtime locales only")
    return "slk", "sk"


def azure_endpoint(value: str) -> str:
    endpoint = value.rstrip("/")
    return endpoint.removesuffix("/openai/v1")


def llm_behavior_options(runtime: EffectiveVoiceRuntime) -> dict[str, object]:
    if model_supports_reasoning(runtime.llm.model):
        return (
            {"reasoning_effort": runtime.llm.reasoning_effort}
            if runtime.llm.reasoning_effort is not None
            else {}
        )
    return (
        {"temperature": runtime.llm.temperature}
        if runtime.llm.temperature is not None
        else {}
    )


def create_agent_session(
    settings: VoiceAgentSettings,
    runtime: EffectiveVoiceRuntime,
    prompt_cache_key: str,
    metrics: VoiceMetrics | None = None,
    secrets: dict[str, str] | None = None,
    snapshot_runtime: dict[str, Any] | None = None,
) -> agents.AgentSession:
    secrets = secrets or {}
    if runtime.llm.provider != "azure_openai":
        raise ValueError(f"unsupported LLM provider: {runtime.llm.provider}")
    if runtime.stt.provider != "elevenlabs":
        raise ValueError(f"unsupported STT provider: {runtime.stt.provider}")
    if runtime.tts.provider != "elevenlabs":
        raise ValueError(f"unsupported TTS provider: {runtime.tts.provider}")
    stt_language, tts_language = provider_languages(runtime.locale)
    connect_options = agents.APIConnectOptions(
        timeout=settings.provider_timeout_seconds,
        max_retry=settings.provider_retry_limit,
    )
    server_vad: NotGivenOr[VADOptions] = NOT_GIVEN
    keyterms: NotGivenOr[list[str]] = (
        runtime.stt.keyterms if runtime.stt.keyterms else NOT_GIVEN
    )
    if not runtime.stt.local_vad_commit.enabled:
        server_vad = {
            "vad_silence_threshold_secs": runtime.stt.server_vad.silence_threshold_seconds,
            "vad_threshold": runtime.stt.server_vad.activity_threshold,
            "min_speech_duration_ms": runtime.stt.server_vad.min_speech_ms,
            "min_silence_duration_ms": runtime.stt.server_vad.min_silence_ms,
        }
    provider_stt = elevenlabs.STT(
        api_key=secrets["stt"],
        model=runtime.stt.model,
        language_code=stt_language,
        keyterms=keyterms,
        server_vad=server_vad,
    )
    stt: livekit_stt.STT = provider_stt
    commit_controller: LocalVadCommitController | None = None
    if runtime.stt.local_vad_commit.enabled:
        commit_controller = LocalVadCommitController(metrics)
        stt = LocalVadCommitSTT(provider_stt, commit_controller)
    vad = inference.VAD(
        min_speech_duration=runtime.local_vad.min_speech_seconds,
        min_silence_duration=runtime.local_vad.min_silence_seconds,
        activation_threshold=runtime.local_vad.activation_threshold,
    )
    if snapshot_runtime is None:
        raise ValueError("snapshot LLM configuration is unavailable")
    deployment = _runtime_value(snapshot_runtime, "llm", "deployment_name")
    endpoint = _runtime_value(snapshot_runtime, "llm", "endpoint")
    api_version = _runtime_value(snapshot_runtime, "llm", "api_version")
    if not deployment or not endpoint or not api_version:
        raise ValueError("snapshot LLM configuration is unavailable")
    llm_provider = openai.LLM.with_azure(
        model=runtime.llm.model,
        azure_deployment=deployment,
        azure_endpoint=azure_endpoint(endpoint),
        api_version=api_version,
        api_key=secrets["llm"],
        prompt_cache_key=prompt_cache_key,
        timeout=httpx.Timeout(settings.provider_timeout_seconds),
        max_completion_tokens=runtime.llm.max_completion_tokens,
        **llm_behavior_options(runtime),  # type: ignore[arg-type]
    )
    tts = elevenlabs.TTS(
        api_key=secrets["tts"],
        model=runtime.tts.model,
        voice_id=runtime.tts.voice_id,
        language=tts_language,
        word_tokenizer=tokenize.blingfire.SentenceTokenizer(
            min_sentence_len=runtime.tts.min_sentence_chars
        ),
    )
    if metrics is not None:
        for component, name in ((stt, "stt"), (llm_provider, "llm"), (tts, "tts")):
            component.on("metrics_collected", metrics.record_component_metric)
            component.on(
                "error",
                lambda error, component_name=name: metrics.record_component_error(
                    component_name, error
                ),
            )
    session: agents.AgentSession = agents.AgentSession(
        stt=stt,
        vad=vad,
        turn_handling={
            "turn_detection": runtime.turn.detection,
            "endpointing": {
                "mode": "fixed",
                "min_delay": runtime.turn.min_endpointing_delay_seconds,
                "max_delay": runtime.turn.max_endpointing_delay_seconds,
            },
            "preemptive_generation": {
                "enabled": runtime.response_scheduling.preemptive_generation,
                "preemptive_tts": runtime.response_scheduling.preemptive_tts,
            },
            "interruption": {
                "enabled": runtime.interruption.enabled,
                "min_duration": runtime.interruption.min_duration_seconds,
                "min_words": runtime.interruption.min_words,
                "false_interruption_timeout": runtime.interruption.false_interruption_timeout_seconds,
                "resume_false_interruption": runtime.interruption.resume_after_false_interruption,
            },
        },
        llm=llm_provider,
        tts=tts,
        tools=[],
        conn_options=SessionConnectOptions(
            stt_conn_options=connect_options,
            llm_conn_options=connect_options,
            tts_conn_options=connect_options,
        ),
    )
    if commit_controller is not None:
        commit_controller.attach(session)
    return session


def create_realtime_session(
    settings: VoiceAgentSettings,
    runtime: dict[str, Any],
    secrets: dict[str, str],
) -> agents.AgentSession:
    model = runtime["model"]
    transcription = runtime["input_transcription"]
    deployment = model["resource"]["deployment"]["deployment_config"]
    connection = model["resource"]["connection"]["connection_config"]
    transcription_config = transcription["resource"]["deployment"]["deployment_config"]
    realtime_model = realtime.RealtimeModel(  # type: ignore[call-overload]
        # The realtime deployment contract intentionally has no logical model field.
        model=deployment.get("model", "gpt-realtime"),
        voice=_required_string(runtime, "voice"),
        azure_deployment=_required_string(deployment, "deployment_name"),
        base_url=f"{azure_endpoint(_required_string(connection, 'endpoint'))}/openai",
        api_version=deployment.get("api_version") or connection.get("api_version"),
        api_key=secrets["model"],
        input_audio_transcription={
            "model": _required_string(transcription_config, "model", "deployment_name"),
            "language": _required_string(runtime["input_transcription"], "language"),
        },
        conn_options=agents.APIConnectOptions(
            timeout=settings.provider_timeout_seconds,
            max_retry=settings.provider_retry_limit,
        ),
    )
    return agents.AgentSession(
        llm=realtime_model,
        vad=None,
        turn_detection=None,
        tools=[],
    )


def _required_string(
    value: dict[str, Any], key: str, fallback_key: str | None = None
) -> str:
    result = value.get(key)
    if result is None and fallback_key is not None:
        result = value.get(fallback_key)
    if not isinstance(result, str) or not result:
        raise ValueError(f"missing realtime execution field: {key}")
    return result


def _runtime_value(
    runtime: dict[str, Any] | None, component: str, key: str
) -> str | None:
    if not runtime:
        return None
    resource = runtime.get(component, {}).get("resource", {})
    deployment = resource.get("deployment", {}).get("deployment_config", {})
    connection = resource.get("connection", {}).get("connection_config", {})
    return deployment.get(key) or connection.get(key)
