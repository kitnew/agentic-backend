import inspect
import logging
import os

from livekit.agents import Agent, AgentSession, stt
from livekit.plugins import elevenlabs


logger = logging.getLogger(__name__)


class StableElevenLabsSTT(elevenlabs.STT):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._accept_interim = True

    def mark_speech_started(self) -> None:
        self._accept_interim = True

    def stream(self, **kwargs):
        return _PostFinalStream(super().stream(**kwargs), self)


class _PostFinalStream:
    def __init__(self, stream, provider):
        self._stream = stream
        self._provider = provider

    def __getattr__(self, name):
        return getattr(self._stream, name)

    def __aiter__(self):
        return self

    async def __anext__(self):
        while True:
            event = await anext(self._stream)
            if event.type == stt.SpeechEventType.FINAL_TRANSCRIPT:
                self._provider._accept_interim = False
                return event
            if event.type in {
                stt.SpeechEventType.START_OF_SPEECH,
                stt.SpeechEventType.INTERIM_TRANSCRIPT,
            } and not self._provider._accept_interim:
                continue
            return event

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        await self._stream.aclose()


def resolve_voice_id(tenant) -> str:
    if tenant.voice.tts.voice_id:
        return tenant.voice.tts.voice_id
    if voice_id := os.getenv("ELEVENLABS_VOICE_ID", "").strip():
        return voice_id
    if voice_id := os.getenv("EVELENLABS_VOICE_ID", "").strip():
        logger.warning("EVELENLABS_VOICE_ID is deprecated; use ELEVENLABS_VOICE_ID")
        return voice_id
    raise ValueError("ElevenLabs voice ID is not configured")


def build_session(settings, tenant, vad) -> AgentSession:
    return AgentSession(
        stt=StableElevenLabsSTT(
            api_key=settings.elevenlabs_api_key,
            model_id=settings.realtime_stt_model,
            language_code=tenant.voice.stt.language or tenant.default_language,
            include_timestamps=True,
            server_vad={
                "vad_silence_threshold_secs": settings.stt_vad_silence_threshold,
                "vad_threshold": settings.stt_vad_threshold,
                "min_speech_duration_ms": settings.stt_min_speech_duration_ms,
                "min_silence_duration_ms": settings.stt_min_silence_duration_ms,
            },
            enable_logging=False,
        ),
        tts=elevenlabs.TTS(
            api_key=settings.elevenlabs_api_key,
            voice_id=resolve_voice_id(tenant),
            model=tenant.voice.tts.model,
            language=tenant.voice.tts.language or tenant.default_language,
            auto_mode=True,
            enable_logging=False,
        ),
        vad=vad,
        turn_handling={
            "turn_detection": "vad",
            "endpointing": {
                "mode": "fixed",
                "min_delay": settings.min_endpointing_delay,
                "max_delay": settings.max_endpointing_delay,
            },
            "interruption": {
                "enabled": True,
                "mode": "vad",
                "discard_audio_if_uninterruptible": True,
                "min_duration": settings.min_interruption_duration,
                "min_words": settings.min_interruption_words,
                "false_interruption_timeout": settings.false_interruption_timeout,
                "resume_false_interruption": settings.resume_false_interruption,
            },
            "preemptive_generation": {"enabled": False},
        },
    )


class HospitalityAgent(Agent):
    def __init__(self, adapter, telemetry):
        super().__init__(instructions="", llm=adapter, tools=[])
        self.adapter = adapter
        self.telemetry = telemetry

    async def llm_node(self, chat_ctx, tools, model_settings):
        message = next(
            item
            for item in reversed(chat_ctx.items)
            if getattr(item, "role", None) == "user"
        )
        text = message.text_content or ""
        if not any(character.isalnum() for character in text):
            return
        async for chunk in self.adapter.stream_turn(text, message.id):
            yield chunk

    async def tts_node(self, text, model_settings):
        stream = Agent.default.tts_node(self, text, model_settings)
        if inspect.isawaitable(stream):
            stream = await stream
        if stream is None:
            return
        first = True
        async for frame in stream:
            if first:
                first = False
                self.telemetry.emit("tts_first_audio")
            yield frame
