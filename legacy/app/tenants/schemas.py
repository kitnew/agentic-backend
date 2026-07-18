from typing import Any

from pydantic import BaseModel, Field


class TenantCapabilityConfig(BaseModel):
    enabled: bool
    provider: str
    config: dict[str, Any] = Field(default_factory=dict)


class TenantAgentConfig(BaseModel):
    profile: str
    display_name: str | None = None
    use_display_name: bool = False
    greeting_phrase: str | None = None
    tone: str | None = None
    language: str | None = None
    style_rules: list[str] = Field(default_factory=list)


class TenantPromptConfig(BaseModel):
    tenant_instructions: str = ""


class TenantBusinessInfoConfig(BaseModel):
    opening_hours_text: str | None = None
    parking: str | None = None
    address: str | None = None
    phone: str | None = None
    menu_summary: str | None = None


class TenantReservationFieldConfig(BaseModel):
    required: bool = True
    label: str


class TenantScheduleInterval(BaseModel):
    start: str
    end: str


class TenantWeeklyScheduleDay(BaseModel):
    open: bool
    intervals: list[TenantScheduleInterval] = Field(default_factory=list)


class TenantReservationScheduleConfig(BaseModel):
    weekly: dict[str, TenantWeeklyScheduleDay] = Field(default_factory=dict)


class TenantReservationConfig(BaseModel):
    enabled: bool = True
    mode: str = "request_only"
    requires_human_confirmation: bool = True
    can_confirm_reservation: bool = False
    required_fields: dict[str, TenantReservationFieldConfig] = Field(default_factory=dict)
    schedule: TenantReservationScheduleConfig = Field(default_factory=TenantReservationScheduleConfig)


class TenantVoiceSTTConfig(BaseModel):
    provider: str = "elevenlabs"
    model: str = "scribe_v2"
    language: str | None = None
    keyterms: list[str] = Field(default_factory=list)


class TenantVoiceTTSConfig(BaseModel):
    provider: str = "elevenlabs"
    model: str = "eleven_flash_v2_5"
    voice_id: str | None = None
    output_format: str = "mp3_44100_128"
    language: str | None = None


class TenantVoiceFallbackConfig(BaseModel):
    send_text_if_tts_fails: bool = True
    continue_if_stt_metadata_missing: bool = True


class TenantVoiceConfig(BaseModel):
    enabled: bool = False
    max_file_size_bytes: int = 25 * 1024 * 1024
    supported_content_types: list[str] = Field(
        default_factory=lambda: [
            "audio/aac",
            "audio/flac",
            "audio/m4a",
            "audio/mp4",
            "audio/mpeg",
            "audio/mp3",
            "audio/ogg",
            "audio/wav",
            "audio/webm",
            "audio/x-m4a",
            "audio/x-wav",
            "video/mp4",
            "video/webm",
        ]
    )
    stt: TenantVoiceSTTConfig = Field(default_factory=TenantVoiceSTTConfig)
    tts: TenantVoiceTTSConfig = Field(default_factory=TenantVoiceTTSConfig)
    fallback: TenantVoiceFallbackConfig = Field(default_factory=TenantVoiceFallbackConfig)


class TenantContext(BaseModel):
    tenant_id: str
    name: str
    business_type: str
    default_language: str
    locale: str | None = None
    timezone: str
    agent: TenantAgentConfig
    prompt: TenantPromptConfig = Field(default_factory=TenantPromptConfig)
    business_info: TenantBusinessInfoConfig = Field(default_factory=TenantBusinessInfoConfig)
    reservation: TenantReservationConfig = Field(default_factory=TenantReservationConfig)
    capabilities: dict[str, TenantCapabilityConfig] = Field(default_factory=dict)
    voice: TenantVoiceConfig = Field(default_factory=TenantVoiceConfig)
