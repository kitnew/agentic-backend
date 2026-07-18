import os
from dataclasses import dataclass
from urllib.parse import urlparse


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes"}


def _number(name: str, default, cast):
    value = os.getenv(name)
    return default if value is None else cast(value)


@dataclass(frozen=True)
class LiveKitSettings:
    enabled: bool = False
    api_key: str = ""
    api_secret: str = ""
    internal_url: str = "ws://livekit:7880"
    public_url: str = "ws://localhost:7880"
    agent_name: str = "hospitality-voice"
    participant_token_ttl_seconds: int = 120
    host: str = "0.0.0.0"
    port: int = 8081
    elevenlabs_api_key: str = ""
    realtime_stt_model: str = "scribe_v2_realtime"
    stt_vad_silence_threshold: float = 1.50
    stt_vad_threshold: float = 0.40
    stt_min_speech_duration_ms: int = 100
    stt_min_silence_duration_ms: int = 100
    min_speech_duration: float = 0.10
    min_silence_duration: float = 0.55
    prefix_padding_duration: float = 0.50
    vad_activation_threshold: float = 0.50
    min_endpointing_delay: float = 0.70
    max_endpointing_delay: float = 2.50
    min_interruption_duration: float = 0.20
    min_interruption_words: int = 1
    false_interruption_timeout: float = 1.0
    resume_false_interruption: bool = False

    @classmethod
    def from_env(cls) -> "LiveKitSettings":
        return cls(
            enabled=_bool("VOICE_LIVEKIT_ENABLED"),
            api_key=os.getenv("LIVEKIT_API_KEY", "").strip(),
            api_secret=os.getenv("LIVEKIT_API_SECRET", "").strip(),
            internal_url=os.getenv("LIVEKIT_INTERNAL_URL", cls.internal_url).strip(),
            public_url=os.getenv("LIVEKIT_PUBLIC_URL", cls.public_url).strip(),
            agent_name=os.getenv("LIVEKIT_AGENT_NAME", cls.agent_name).strip(),
            participant_token_ttl_seconds=_number(
                "LIVEKIT_PARTICIPANT_TOKEN_TTL_SECONDS", cls.participant_token_ttl_seconds, int
            ),
            host=os.getenv("LIVEKIT_AGENT_HOST", cls.host).strip(),
            port=_number("LIVEKIT_AGENT_PORT", cls.port, int),
            elevenlabs_api_key=os.getenv("ELEVENLABS_API_KEY", "").strip(),
            realtime_stt_model=os.getenv(
                "ELEVENLABS_REALTIME_STT_MODEL", cls.realtime_stt_model
            ).strip(),
            stt_vad_silence_threshold=_number(
                "VOICE_LIVEKIT_STT_VAD_SILENCE_THRESHOLD_SECONDS",
                cls.stt_vad_silence_threshold,
                float,
            ),
            stt_vad_threshold=_number(
                "VOICE_LIVEKIT_STT_VAD_THRESHOLD", cls.stt_vad_threshold, float
            ),
            stt_min_speech_duration_ms=_number(
                "VOICE_LIVEKIT_STT_MIN_SPEECH_DURATION_MS",
                cls.stt_min_speech_duration_ms,
                int,
            ),
            stt_min_silence_duration_ms=_number(
                "VOICE_LIVEKIT_STT_MIN_SILENCE_DURATION_MS",
                cls.stt_min_silence_duration_ms,
                int,
            ),
            min_speech_duration=_number(
                "VOICE_LIVEKIT_MIN_SPEECH_DURATION_SECONDS", cls.min_speech_duration, float
            ),
            min_silence_duration=_number(
                "VOICE_LIVEKIT_MIN_SILENCE_DURATION_SECONDS", cls.min_silence_duration, float
            ),
            prefix_padding_duration=_number(
                "VOICE_LIVEKIT_PREFIX_PADDING_SECONDS", cls.prefix_padding_duration, float
            ),
            vad_activation_threshold=_number(
                "VOICE_LIVEKIT_VAD_ACTIVATION_THRESHOLD", cls.vad_activation_threshold, float
            ),
            min_endpointing_delay=_number(
                "VOICE_LIVEKIT_MIN_ENDPOINTING_DELAY_SECONDS", cls.min_endpointing_delay, float
            ),
            max_endpointing_delay=_number(
                "VOICE_LIVEKIT_MAX_ENDPOINTING_DELAY_SECONDS", cls.max_endpointing_delay, float
            ),
            min_interruption_duration=_number(
                "VOICE_LIVEKIT_MIN_INTERRUPTION_DURATION_SECONDS",
                cls.min_interruption_duration,
                float,
            ),
            min_interruption_words=_number(
                "VOICE_LIVEKIT_MIN_INTERRUPTION_WORDS", cls.min_interruption_words, int
            ),
            false_interruption_timeout=_number(
                "VOICE_LIVEKIT_FALSE_INTERRUPTION_TIMEOUT_SECONDS",
                cls.false_interruption_timeout,
                float,
            ),
            resume_false_interruption=_bool("VOICE_LIVEKIT_RESUME_FALSE_INTERRUPTION"),
        )

    def validate_api(self) -> None:
        if not self.api_key or len(self.api_secret.encode()) < 32:
            raise ValueError("LIVEKIT_API_KEY and a 32-byte LIVEKIT_API_SECRET are required")
        for name in ("internal_url", "public_url"):
            parsed = urlparse(getattr(self, name))
            if parsed.scheme not in {"ws", "wss"} or not parsed.netloc or parsed.username:
                raise ValueError(f"{name} must be an absolute ws:// or wss:// URL")
        if not self.agent_name or self.participant_token_ttl_seconds <= 0:
            raise ValueError("LIVEKIT_AGENT_NAME and a positive token TTL are required")

    def validate_worker(self) -> None:
        self.validate_api()
        if not self.elevenlabs_api_key or not self.realtime_stt_model:
            raise ValueError("ELEVENLABS_API_KEY and realtime STT model are required")
        durations = (
            self.min_speech_duration,
            self.min_silence_duration,
            self.prefix_padding_duration,
            self.min_endpointing_delay,
            self.max_endpointing_delay,
            self.min_interruption_duration,
            self.false_interruption_timeout,
            self.stt_vad_silence_threshold,
            self.stt_min_speech_duration_ms,
            self.stt_min_silence_duration_ms,
        )
        if min(durations) <= 0 or self.min_endpointing_delay > self.max_endpointing_delay:
            raise ValueError("LiveKit VAD and endpointing durations must be positive and ordered")
        if (
            not 0 < self.vad_activation_threshold <= 1
            or not 0 < self.stt_vad_threshold <= 1
            or self.min_interruption_words < 0
            or not 1 <= self.port <= 65535
        ):
            raise ValueError("LiveKit VAD threshold or agent port is invalid")
