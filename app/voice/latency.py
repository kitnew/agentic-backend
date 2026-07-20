from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _VoiceConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class VadConfig(_VoiceConfigModel):
    activation_threshold: float = Field(
        0.5, gt=0, le=1,
        description="Silero speech probability threshold. Lower reacts more easily but increases false starts; higher rejects noise but may miss quiet speech. SDK: activation_threshold.",
    )
    min_speech_ms: int = Field(
        100, ge=50, le=2000,
        description="Minimum detected speech. Lower reacts faster but accepts clicks; higher is safer but can miss short words. SDK seconds: min_speech_duration.",
    )
    min_silence_ms: int = Field(
        550, ge=50, le=3000,
        description="Silence before Silero ends speech. Lower responds faster but cuts pauses; higher preserves pauses but adds delay. SDK seconds: min_silence_duration.",
    )
    prefix_padding_ms: int = Field(
        500, ge=0, le=2000,
        description="Audio retained before speech start. Lower uses less context but may clip initials; higher is safer but buffers more audio. SDK seconds: prefix_padding_duration.",
    )


class EndpointingConfig(_VoiceConfigModel):
    min_delay_ms: int = Field(
        700, ge=100, le=5000,
        description="Minimum end-of-turn wait. Lower responds faster but risks cutting pauses; higher is safer but slower. SDK seconds: min_endpointing_delay.",
    )
    max_delay_ms: int = Field(
        2500, ge=100, le=10000,
        description="Maximum end-of-turn wait. Lower caps latency but may interrupt slow speakers; higher permits longer pauses. SDK seconds: max_endpointing_delay.",
    )

    @model_validator(mode="after")
    def validate_order(self):
        if self.min_delay_ms > self.max_delay_ms:
            raise ValueError("min_delay_ms must not exceed max_delay_ms")
        return self


class InterruptionConfig(_VoiceConfigModel):
    enabled: bool = Field(True, description="Allow caller speech to interrupt assistant playback. SDK: allow_interruptions.")
    min_duration_ms: int = Field(
        200, ge=0, le=3000,
        description="Speech required to interrupt. Lower barges in faster but reacts to noise; higher is safer but slower. SDK seconds: min_interruption_duration.",
    )
    min_words: int = Field(
        1, ge=0, le=20,
        description="Transcript words required to interrupt. Lower is faster but noisier; higher needs clearer speech. SDK: min_interruption_words.",
    )
    false_interruption_timeout_ms: int = Field(
        1000, ge=100, le=10000,
        description="Wait before treating an interruption as false. Lower decides sooner; higher allows slower speech but delays recovery. SDK seconds: false_interruption_timeout.",
    )
    resume_after_false_interruption: bool = Field(
        False, description="Resume interrupted speech after a false interruption. SDK: resume_false_interruption."
    )


class SttSegmentationConfig(_VoiceConfigModel):
    enabled: bool = Field(True, description="Enable ElevenLabs server VAD for Scribe realtime.")
    silence_ms: int | None = Field(
        400, ge=100, le=5000,
        description="Server-VAD silence before commit. Lower finalizes faster but cuts pauses; higher is safer but slower. SDK seconds: vad_silence_threshold_secs.",
    )
    threshold: float | None = Field(
        0.4, gt=0, le=1,
        description="ElevenLabs VAD probability threshold. Lower is more sensitive; higher rejects noise but may miss quiet speech. SDK: vad_threshold.",
    )
    min_speech_ms: int | None = Field(
        100, ge=0, le=5000,
        description="Minimum provider speech segment. Lower accepts short sounds; higher rejects them. SDK: min_speech_duration_ms.",
    )
    min_silence_ms: int | None = Field(
        100, ge=0, le=5000,
        description="Minimum provider silence segment. Lower reacts sooner; higher reduces fragmented segments. SDK: min_silence_duration_ms.",
    )


class VoiceTurnConfig(_VoiceConfigModel):
    vad: VadConfig = Field(default_factory=VadConfig)
    endpointing: EndpointingConfig = Field(default_factory=EndpointingConfig)
    interruption: InterruptionConfig = Field(default_factory=InterruptionConfig)
    stt_segmentation: SttSegmentationConfig = Field(default_factory=SttSegmentationConfig)

    def sanitized(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class VadOverrides(_VoiceConfigModel):
    activation_threshold: float | None = Field(None, gt=0, le=1)
    min_speech_ms: int | None = Field(None, ge=50, le=2000)
    min_silence_ms: int | None = Field(None, ge=50, le=3000)
    prefix_padding_ms: int | None = Field(None, ge=0, le=2000)


class EndpointingOverrides(_VoiceConfigModel):
    min_delay_ms: int | None = Field(None, ge=100, le=5000)
    max_delay_ms: int | None = Field(None, ge=100, le=10000)


class InterruptionOverrides(_VoiceConfigModel):
    enabled: bool | None = None
    min_duration_ms: int | None = Field(None, ge=0, le=3000)
    min_words: int | None = Field(None, ge=0, le=20)
    false_interruption_timeout_ms: int | None = Field(None, ge=100, le=10000)
    resume_after_false_interruption: bool | None = None


class SttSegmentationOverrides(_VoiceConfigModel):
    enabled: bool | None = None
    silence_ms: int | None = Field(None, ge=100, le=5000)
    threshold: float | None = Field(None, gt=0, le=1)
    min_speech_ms: int | None = Field(None, ge=0, le=5000)
    min_silence_ms: int | None = Field(None, ge=0, le=5000)


class VoiceTurnOverrides(_VoiceConfigModel):
    vad: VadOverrides | None = None
    endpointing: EndpointingOverrides | None = None
    interruption: InterruptionOverrides | None = None
    stt_segmentation: SttSegmentationOverrides | None = None


def resolve_voice_turn_config(
    tenant_config: VoiceTurnConfig | None = None,
    session_overrides: VoiceTurnOverrides | None = None,
) -> VoiceTurnConfig:
    values = (tenant_config or VoiceTurnConfig()).model_dump()
    if session_overrides:
        for group, overrides in session_overrides.model_dump(exclude_none=True).items():
            values[group].update(overrides)
    return VoiceTurnConfig.model_validate(values)
