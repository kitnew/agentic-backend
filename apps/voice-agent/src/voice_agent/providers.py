from typing import Any

import httpx
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


def llm_behavior_options(runtime: dict[str, Any]) -> dict[str, object]:
    llm = runtime["llm"]
    model = str(
        llm["deployment_config"].get(
            "model", llm["deployment_config"].get("deployment_name", "")
        )
    )
    if model.rsplit("/", 1)[-1].lower().startswith(("gpt-5", "o1", "o3", "o4")):
        return (
            {"reasoning_effort": llm["reasoning_effort"]}
            if llm.get("reasoning_effort") is not None
            else {}
        )
    return (
        {"temperature": llm["temperature"]}
        if llm.get("temperature") is not None
        else {}
    )


def create_agent_session(
    settings: VoiceAgentSettings,
    runtime: dict[str, Any],
    prompt_cache_key: str,
    metrics: VoiceMetrics | None = None,
    secrets: dict[str, str] | None = None,
) -> agents.AgentSession:
    secrets = secrets or {}
    llm = runtime["llm"]
    stt_config = runtime["stt"]
    tts_config = runtime["tts"]
    if llm["provider_kind"] != "azure_openai":
        raise ValueError(f"unsupported LLM provider: {llm['provider_kind']}")
    if stt_config["provider_kind"] != "elevenlabs":
        raise ValueError(f"unsupported STT provider: {stt_config['provider_kind']}")
    if tts_config["provider_kind"] != "elevenlabs":
        raise ValueError(f"unsupported TTS provider: {tts_config['provider_kind']}")
    stt_language, tts_language = provider_languages(str(runtime["locale"]))
    connect_options = agents.APIConnectOptions(
        timeout=settings.provider_timeout_seconds,
        max_retry=settings.provider_retry_limit,
    )
    server_vad: NotGivenOr[VADOptions] = NOT_GIVEN
    keyterms: NotGivenOr[list[str]] = (
        stt_config["speech_hints"]["keyterms"]["values"] or NOT_GIVEN
    )
    commit = stt_config["commit"]
    server = commit.get("provider_vad", {})
    if commit["strategy"] != "local_vad":
        server_vad = {
            "vad_silence_threshold_secs": server.get("silence_threshold_seconds", 0.5),
            "vad_threshold": server.get("threshold", 0.5),
            "min_speech_duration_ms": server.get("min_speech_ms", 100),
            "min_silence_duration_ms": server.get("min_silence_ms", 250),
        }
    provider_stt = elevenlabs.STT(
        api_key=secrets["stt"],
        model=stt_config["deployment_config"].get(
            "model_id", stt_config["deployment_config"].get("model")
        ),
        language_code=stt_language,
        keyterms=keyterms,
        server_vad=server_vad,
    )
    stt: livekit_stt.STT = provider_stt
    commit_controller: LocalVadCommitController | None = None
    if commit["strategy"] == "local_vad":
        commit_controller = LocalVadCommitController(metrics)
        stt = LocalVadCommitSTT(provider_stt, commit_controller)
    speech_activity = stt_config["speech_activity"]
    vad = inference.VAD(
        min_speech_duration=speech_activity["min_speech_seconds"],
        min_silence_duration=speech_activity["min_silence_seconds"],
        activation_threshold=speech_activity["activation_threshold"],
    )
    deployment = _runtime_value(runtime, "llm", "deployment_name")
    endpoint = _runtime_value(runtime, "llm", "endpoint")
    api_version = _runtime_value(runtime, "llm", "api_version")
    if not deployment or not endpoint or not api_version:
        raise ValueError("execution LLM configuration is unavailable")
    llm_provider = openai.LLM.with_azure(
        model=llm["deployment_config"].get(
            "model", llm["deployment_config"].get("deployment_name")
        ),
        azure_deployment=deployment,
        azure_endpoint=azure_endpoint(endpoint),
        api_version=api_version,
        api_key=secrets["llm"],
        prompt_cache_key=prompt_cache_key,
        timeout=httpx.Timeout(settings.provider_timeout_seconds),
        max_completion_tokens=llm["max_completion_tokens"],
        **llm_behavior_options(runtime),  # type: ignore[arg-type]
    )
    tts = elevenlabs.TTS(
        api_key=secrets["tts"],
        model=tts_config["deployment_config"].get(
            "model_id", tts_config["deployment_config"].get("model")
        ),
        voice_id=tts_config["voice"],
        language=tts_language,
        word_tokenizer=tokenize.blingfire.SentenceTokenizer(
            min_sentence_len=tts_config["tokenizer"]["min_sentence_chars"]
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
            "turn_detection": "stt",
            "endpointing": {
                "mode": "fixed",
                "min_delay": stt_config["endpointing"]["min_delay_seconds"],
                "max_delay": stt_config["endpointing"]["max_delay_seconds"],
            },
            "preemptive_generation": {
                "enabled": llm["response_scheduling"]["preemptive_generation"],
                "preemptive_tts": llm["response_scheduling"]["preemptive_tts"],
            },
            "interruption": {
                "enabled": llm["interruption"]["enabled"],
                "min_duration": llm["interruption"]["min_duration_seconds"],
                "min_words": llm["interruption"]["min_words"],
                "false_interruption_timeout": llm["interruption"][
                    "false_interruption_timeout_seconds"
                ],
                "resume_false_interruption": llm["interruption"][
                    "resume_after_false_interruption"
                ],
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
    deployment = model["deployment_config"]
    connection = model["connection_config"]
    transcription_config = transcription["deployment_config"]
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
        turn_detection=NOT_GIVEN,
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
    value = runtime.get(component, {})
    deployment = value.get("deployment_config", {})
    connection = value.get("connection_config", {})
    return deployment.get(key) or connection.get(key)
