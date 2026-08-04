import httpx
from livekit import agents
from livekit.agents import inference
from livekit.agents.voice.agent_session import SessionConnectOptions
from livekit.plugins import elevenlabs, openai

from voice_agent.settings import VoiceAgentSettings


def tts_language(locale: str) -> str:
    language = locale.partition("-")[0].lower()
    if language != "sk":
        raise ValueError("the voice deployment supports Slovak runtime locales only")
    return language


def azure_endpoint(value: str) -> str:
    endpoint = value.rstrip("/")
    return endpoint.removesuffix("/openai/v1")


def create_agent_session(
    settings: VoiceAgentSettings,
    locale: str,
) -> agents.AgentSession:
    connect_options = agents.APIConnectOptions(
        timeout=settings.provider_timeout_seconds,
        max_retry=settings.provider_retry_limit,
    )
    return agents.AgentSession(
        stt=elevenlabs.STT(
            api_key=settings.elevenlabs_api_key.get_secret_value(),
            model="scribe_v2_realtime",
            language_code="slk",
            server_vad={
                "vad_silence_threshold_secs": 0.5,
                "vad_threshold": 0.35,
                "min_speech_duration_ms": 100,
                "min_silence_duration_ms": 500,
            },
        ),
        vad=inference.VAD(
            min_speech_duration=0.05,
            min_silence_duration=0.25,
            activation_threshold=0.5,
        ),
        turn_handling={
            "turn_detection": "stt",
            "endpointing": {"mode": "fixed", "min_delay": 0.1, "max_delay": 0.7},
        },
        llm=openai.LLM.with_azure(
            model=settings.azure_openai_deployment,
            azure_deployment=settings.azure_openai_deployment,
            azure_endpoint=azure_endpoint(settings.azure_openai_endpoint),
            api_version=settings.azure_openai_api_version,
            api_key=settings.azure_openai_api_key.get_secret_value(),
            timeout=httpx.Timeout(settings.provider_timeout_seconds),
            temperature=0,
        ),
        tts=elevenlabs.TTS(
            api_key=settings.elevenlabs_api_key.get_secret_value(),
            model="eleven_flash_v2_5",
            voice_id=settings.elevenlabs_voice_id,
            language=tts_language(locale),
        ),
        tools=[],
        conn_options=SessionConnectOptions(
            stt_conn_options=connect_options,
            llm_conn_options=connect_options,
            tts_conn_options=connect_options,
        ),
    )
