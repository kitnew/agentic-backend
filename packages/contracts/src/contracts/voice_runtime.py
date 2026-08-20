from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator


class _RuntimeModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )


Identifier = Annotated[str, Field(min_length=1, max_length=255)]
Threshold = Annotated[FiniteFloat, Field(ge=0, le=1)]


class LLMRuntimeSettings(_RuntimeModel):
    provider: Literal["azure_openai"]
    model: Identifier
    temperature: Annotated[FiniteFloat, Field(ge=0, le=2)]


class ServerVADRuntimeSettings(_RuntimeModel):
    silence_threshold_seconds: Annotated[FiniteFloat, Field(gt=0, le=60)]
    activity_threshold: Threshold
    min_speech_ms: int = Field(gt=0, le=60_000)
    min_silence_ms: int = Field(gt=0, le=60_000)


class STTRuntimeSettings(_RuntimeModel):
    provider: Literal["elevenlabs"]
    model: Identifier
    server_vad: ServerVADRuntimeSettings


class TTSRuntimeSettings(_RuntimeModel):
    provider: Literal["elevenlabs"]
    model: Identifier
    voice_id: Identifier


class LocalVADRuntimeSettings(_RuntimeModel):
    min_speech_seconds: Annotated[FiniteFloat, Field(gt=0, le=60)]
    min_silence_seconds: Annotated[FiniteFloat, Field(gt=0, le=60)]
    activation_threshold: Threshold


class TurnRuntimeSettings(_RuntimeModel):
    detection: Literal["stt"]
    min_endpointing_delay_seconds: Annotated[FiniteFloat, Field(gt=0, le=60)]
    max_endpointing_delay_seconds: Annotated[FiniteFloat, Field(gt=0, le=60)]

    @model_validator(mode="after")
    def endpointing_delays_are_ordered(self) -> TurnRuntimeSettings:
        if self.min_endpointing_delay_seconds > self.max_endpointing_delay_seconds:
            raise ValueError(
                "min_endpointing_delay_seconds must not exceed "
                "max_endpointing_delay_seconds"
            )
        return self


class PlatformRuntimePolicy(_RuntimeModel):
    llm: LLMRuntimeSettings
    stt: STTRuntimeSettings
    tts: TTSRuntimeSettings
    local_vad: LocalVADRuntimeSettings
    turn: TurnRuntimeSettings


class TenantTTSRuntimeOverride(_RuntimeModel):
    voice_id: Identifier


class TenantLLMRuntimeOverride(_RuntimeModel):
    model: Identifier


class TenantRuntimeOverride(_RuntimeModel):
    llm: TenantLLMRuntimeOverride | None = None
    tts: TenantTTSRuntimeOverride | None = None


class EffectiveVoiceRuntime(PlatformRuntimePolicy):
    locale: Annotated[
        str,
        Field(min_length=1, max_length=35, pattern=r"^[a-z]{2,3}(?:-[A-Z]{2})?$"),
    ]
