from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    StrictStr,
    field_validator,
    model_validator,
)


class _RuntimeModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )


Identifier = Annotated[str, Field(min_length=1, max_length=255)]
Threshold = Annotated[FiniteFloat, Field(ge=0, le=1)]
ReasoningEffort = Literal["none", "low", "medium", "high", "xhigh", "max"]
STTKeyterm = Annotated[StrictStr, Field(min_length=1, max_length=20)]


def model_supports_reasoning(model: str) -> bool:
    name = model.rsplit("/", 1)[-1].lower()
    return name.startswith(("gpt-5", "o1", "o3", "o4"))


def validate_llm_behavior(
    model: str,
    temperature: FiniteFloat | None,
    reasoning_effort: ReasoningEffort | None,
) -> None:
    if model_supports_reasoning(model):
        if temperature is not None:
            raise ValueError(
                "temperature must be omitted for reasoning models; "
                "use reasoning_effort instead"
            )
    elif reasoning_effort not in (None, "none"):
        raise ValueError(
            "reasoning_effort other than 'none' requires a reasoning model"
        )


class LLMRuntimeSettings(_RuntimeModel):
    provider: Literal["azure_openai"]
    model: Identifier
    temperature: Annotated[FiniteFloat, Field(ge=0, le=2)] | None = None
    reasoning_effort: ReasoningEffort | None = None

    @model_validator(mode="after")
    def provider_parameters_are_compatible(self) -> LLMRuntimeSettings:
        validate_llm_behavior(self.model, self.temperature, self.reasoning_effort)
        return self


class ServerVADRuntimeSettings(_RuntimeModel):
    silence_threshold_seconds: Annotated[FiniteFloat, Field(gt=0, le=60)]
    activity_threshold: Threshold
    min_speech_ms: int = Field(gt=0, le=60_000)
    min_silence_ms: int = Field(gt=0, le=60_000)


class InterimPreflightRuntimeSettings(_RuntimeModel):
    enabled: bool = False
    min_transcript_chars: int = Field(default=20, ge=3, le=500)
    min_growth_chars: int = Field(default=12, ge=1, le=500)
    max_generations_per_turn: int = Field(default=2, ge=1, le=5)


class LocalVADCommitRuntimeSettings(_RuntimeModel):
    enabled: bool = False


class STTRuntimeSettings(_RuntimeModel):
    provider: Literal["elevenlabs"]
    model: Identifier
    server_vad: ServerVADRuntimeSettings
    local_vad_commit: LocalVADCommitRuntimeSettings = Field(
        default_factory=lambda: LocalVADCommitRuntimeSettings(enabled=True)
    )
    interim_preflight: InterimPreflightRuntimeSettings = Field(
        default_factory=InterimPreflightRuntimeSettings
    )


def _canonicalize_keyterms(value: list[str]) -> list[str]:
    if len(value) != len(set(value)):
        raise ValueError("STT keyterms must be unique")
    return sorted(value)


class EffectiveSTTRuntimeSettings(STTRuntimeSettings):
    local_vad_commit: LocalVADCommitRuntimeSettings = Field(
        default_factory=LocalVADCommitRuntimeSettings
    )
    keyterms: list[STTKeyterm] = Field(default_factory=list, max_length=50)

    _canonical_keyterms = field_validator("keyterms")(_canonicalize_keyterms)


class TTSRuntimeSettings(_RuntimeModel):
    provider: Literal["elevenlabs"]
    model: Identifier
    voice_id: Identifier
    min_sentence_chars: int = Field(default=20, ge=3, le=200)


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
    temperature: Annotated[FiniteFloat, Field(ge=0, le=2)] | None = None
    reasoning_effort: ReasoningEffort | None = None

    @model_validator(mode="after")
    def provider_parameters_are_compatible(self) -> TenantLLMRuntimeOverride:
        validate_llm_behavior(self.model, self.temperature, self.reasoning_effort)
        return self


class TenantSTTRuntimeOverride(_RuntimeModel):
    keyterms: list[STTKeyterm] = Field(default_factory=list, max_length=50)

    _canonical_keyterms = field_validator("keyterms")(_canonicalize_keyterms)


class TenantRuntimeOverride(_RuntimeModel):
    llm: TenantLLMRuntimeOverride | None = None
    stt: TenantSTTRuntimeOverride | None = None
    tts: TenantTTSRuntimeOverride | None = None


class EffectiveVoiceRuntime(PlatformRuntimePolicy):
    stt: EffectiveSTTRuntimeSettings
    locale: Annotated[
        str,
        Field(min_length=1, max_length=35, pattern=r"^[a-z]{2,3}(?:-[A-Z]{2})?$"),
    ]

    @field_validator("stt", mode="before")
    @classmethod
    def accept_legacy_stt_settings(cls, value: object) -> object:
        return (
            value.model_dump(mode="json")
            if isinstance(value, STTRuntimeSettings)
            else value
        )
