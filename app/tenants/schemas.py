import re
from datetime import time
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.contracts.voice import VoiceTurnConfig


class TenantModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TenantCapabilityConfig(TenantModel):
    enabled: bool
    provider: str
    config: dict[str, Any] = Field(default_factory=dict)


class TenantAgentConfig(TenantModel):
    profile: str
    display_name: str | None = None
    role: str | None = None
    use_display_name: bool = False
    greeting_phrase: str | None = None
    localized_greetings: dict[str, str] = Field(default_factory=dict)
    tone: str | None = None
    language: str | None = None
    style_rules: list[str] = Field(default_factory=list)


class TenantPromptConfig(TenantModel):
    tenant_instructions: str = ""
    instructions_file: str | None = None
    knowledge_base_files: list[str] = Field(default_factory=list)
    supplementary_files: list[str] = Field(default_factory=list)
    instructions: str = ""
    knowledge_base: str = ""
    supplementary_guidance: list[str] = Field(default_factory=list)


class TenantRoomTypeConfig(TenantModel):
    code: str
    display_name: dict[str, str]
    capacity: int = Field(gt=0)
    inventory_count: int = Field(ge=0)
    unit_price_per_night: Decimal = Field(ge=0)
    currency: str
    single_occupancy_price: Decimal | None = Field(default=None, ge=0)
    notes: list[str] = Field(default_factory=list)

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("room code must not be empty")
        return value

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        if len(value) != 3 or not value.isalpha() or not value.isupper():
            raise ValueError("currency must be an uppercase three-letter code")
        return value


class TenantBusinessInfoConfig(TenantModel):
    property_name: str | None = None
    category: str | None = None
    opening_hours_text: str | None = None
    reception_hours: str | None = None
    parking: str | None = None
    address: str | None = None
    phone: str | None = None
    public_email: str | None = None
    website: str | None = None
    menu_summary: str | None = None
    room_types: list[TenantRoomTypeConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_room_codes(self):
        codes = [room.code for room in self.room_types]
        if len(codes) != len(set(codes)):
            raise ValueError("room type codes must be unique")
        return self


class TenantFeatureConfig(TenantModel):
    factual_qa: bool = False
    room_recommendation: bool = False
    availability_check: bool = False
    reservation_create: bool = False
    reservation_modify: bool = False
    reservation_cancel: bool = False
    reservation_lookup: bool = False
    human_transfer: bool = False


class TenantConversationScopeConfig(TenantModel):
    mode: Literal["unrestricted", "property_only"] = "unrestricted"
    localized_refusals: dict[str, str] = Field(default_factory=dict)
    blocked_phrases: dict[str, list[str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_property_only_policy(self):
        if self.mode == "property_only" and (
            not self.localized_refusals or not self.blocked_phrases
        ):
            raise ValueError(
                "property_only conversation scope requires refusals and blocked phrases"
            )
        return self


def spreadsheet_column_index(column: str) -> int:
    if not re.fullmatch(r"[A-Z]+", column):
        raise ValueError(f"invalid spreadsheet column: {column}")
    index = 0
    for character in column:
        index = index * 26 + ord(character) - ord("A") + 1
    return index - 1


def spreadsheet_column_span(column_range: str) -> tuple[int, int]:
    parts = column_range.split(":")
    if len(parts) != 2:
        raise ValueError(f"invalid spreadsheet column range: {column_range}")
    start, end = (spreadsheet_column_index(part) for part in parts)
    if start > end:
        raise ValueError(f"spreadsheet column range is reversed: {column_range}")
    return start, end


class TenantAvailabilityConfig(TenantModel):
    spreadsheet_id: str
    sheet_name: str
    table_range: str
    header_row: int = Field(gt=0)
    data_start_row: int = Field(gt=0)
    date_column: str
    room_type_columns: dict[str, str]
    free_cell_policy: Literal["blank"]
    stay_interval: Literal["check_in_inclusive_check_out_exclusive"]
    reject_past_check_in: bool = False
    past_check_in_responses: dict[str, str] = Field(default_factory=dict)
    date_formats: list[str] = Field(default_factory=lambda: ["%Y-%m-%d", "%d.%m.%Y"])
    one_night_room_type_fallbacks: dict[str, list[str]] = Field(default_factory=dict)
    announcement: str | None = None

    @field_validator("spreadsheet_id", "sheet_name")
    @classmethod
    def validate_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("date_column")
    @classmethod
    def validate_date_column(cls, value: str) -> str:
        spreadsheet_column_index(value)
        return value

    @field_validator("table_range")
    @classmethod
    def validate_table_range(cls, value: str) -> str:
        spreadsheet_column_span(value)
        return value

    @field_validator("room_type_columns")
    @classmethod
    def validate_room_type_columns(cls, value: dict[str, str]) -> dict[str, str]:
        if not value:
            raise ValueError("room_type_columns must not be empty")
        for room_type, column_range in value.items():
            if not room_type.strip():
                raise ValueError("room type code must not be empty")
            spreadsheet_column_span(column_range)
        return value

    @model_validator(mode="after")
    def validate_layout(self):
        if self.data_start_row <= self.header_row:
            raise ValueError("data_start_row must be after header_row")
        table_start, table_end = spreadsheet_column_span(self.table_range)
        date_index = spreadsheet_column_index(self.date_column)
        if not table_start <= date_index <= table_end:
            raise ValueError("date_column must be inside table_range")
        occupied_columns: set[int] = set()
        for room_type, column_range in self.room_type_columns.items():
            start, end = spreadsheet_column_span(column_range)
            if start < table_start or end > table_end:
                raise ValueError(f"room range for {room_type} must be inside table_range")
            columns = set(range(start, end + 1))
            if occupied_columns & columns:
                raise ValueError("room type column ranges must not overlap")
            occupied_columns.update(columns)
        if not self.date_formats:
            raise ValueError("date_formats must not be empty")
        if self.reject_past_check_in and not self.past_check_in_responses:
            raise ValueError("past check-in rejection requires localized responses")
        for requested, fallbacks in self.one_night_room_type_fallbacks.items():
            if requested not in self.room_type_columns or any(
                fallback not in self.room_type_columns for fallback in fallbacks
            ):
                raise ValueError("room type fallbacks must reference configured room types")
        return self


class TenantPostCallTranscriptConfig(TenantModel):
    spreadsheet_id: str
    sheet_name: str

    @field_validator("spreadsheet_id", "sheet_name")
    @classmethod
    def validate_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value


class TenantReservationFieldConfig(TenantModel):
    required: bool = True
    label: str


class TenantScheduleInterval(TenantModel):
    start: str
    end: str


class TenantWeeklyScheduleDay(TenantModel):
    open: bool
    intervals: list[TenantScheduleInterval] = Field(default_factory=list)


class TenantReservationScheduleConfig(TenantModel):
    weekly: dict[str, TenantWeeklyScheduleDay] = Field(default_factory=dict)


class TenantReservationFlowConfig(TenantModel):
    availability_before_guest_details: bool = False
    ask_to_continue_after_availability: bool = False
    require_final_confirmation: bool = False
    availability_result_ttl_seconds: int = Field(default=900, gt=0)


class TenantReservationContactConfig(TenantModel):
    email_required: bool | None = None
    prefer_inbound_phone_with_consent: bool = False
    inbound_phone_consent_prompt: str | None = None

    @model_validator(mode="after")
    def validate_inbound_phone_policy(self):
        if (
            self.prefer_inbound_phone_with_consent
            and not self.inbound_phone_consent_prompt
        ):
            raise ValueError("inbound phone consent policy requires a prompt")
        return self


class TenantReservationConfig(TenantModel):
    enabled: bool = True
    mode: str = "request_only"
    requires_human_confirmation: bool = True
    can_confirm_reservation: bool = False
    required_fields: dict[str, TenantReservationFieldConfig] = Field(default_factory=dict)
    flow: TenantReservationFlowConfig = Field(default_factory=TenantReservationFlowConfig)
    contact: TenantReservationContactConfig = Field(
        default_factory=TenantReservationContactConfig
    )
    schedule: TenantReservationScheduleConfig = Field(default_factory=TenantReservationScheduleConfig)
    request_cutoff_local_time: time | None = None
    reject_at_or_after_cutoff: bool = True
    cutoff_responses: dict[str, str] = Field(default_factory=dict)
    new_request_phrases: dict[str, list[str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_cutoff_policy(self):
        if self.request_cutoff_local_time and (
            not self.cutoff_responses or not self.new_request_phrases
        ):
            raise ValueError(
                "reservation cutoff requires responses and new request phrases"
            )
        return self


class TenantVoiceSTTConfig(TenantModel):
    provider: str = "elevenlabs"
    model: str = "scribe_v2"
    language: str | None = None
    keyterms: list[str] = Field(default_factory=list)


class TenantVoiceTTSConfig(TenantModel):
    provider: str = "elevenlabs"
    model: str = "eleven_flash_v2_5"
    voice_id: str | None = None
    output_format: str = "mp3_44100_128"
    language: str | None = None


class TenantVoiceFallbackConfig(TenantModel):
    send_text_if_tts_fails: bool = True
    continue_if_stt_metadata_missing: bool = True


def normalize_phone_number(value: str) -> str:
    value = value.strip()
    if not re.fullmatch(r"(?:\+|00)?[0-9(). -]+", value):
        raise ValueError("phone number must contain only digits and common separators")
    digits = "".join(character for character in value if character.isdigit())
    if value.startswith("00"):
        digits = digits[2:]
    if not 8 <= len(digits) <= 15:
        raise ValueError("phone number must contain 8 to 15 digits")
    return f"+{digits}"


class TenantVoiceConfig(TenantModel):
    enabled: bool = False
    inbound_dids: list[str] = Field(default_factory=list)
    end_call_enabled: bool = False
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
    turn: VoiceTurnConfig = Field(default_factory=VoiceTurnConfig)

    @field_validator("inbound_dids")
    @classmethod
    def validate_inbound_dids(cls, value: list[str]) -> list[str]:
        normalized = [normalize_phone_number(number) for number in value]
        if len(normalized) != len(set(normalized)):
            raise ValueError("voice.inbound_dids must not contain duplicates")
        return normalized


class TenantContext(TenantModel):
    schema_version: Literal[2] = 2
    tenant_id: str
    name: str
    business_type: str
    enabled: bool = True
    default_language: str
    supported_locales: list[str]
    locale: str | None = None
    timezone: str
    agent: TenantAgentConfig
    prompt: TenantPromptConfig = Field(default_factory=TenantPromptConfig)
    business_info: TenantBusinessInfoConfig = Field(default_factory=TenantBusinessInfoConfig)
    reservation: TenantReservationConfig = Field(default_factory=TenantReservationConfig)
    features: TenantFeatureConfig = Field(default_factory=TenantFeatureConfig)
    conversation_scope: TenantConversationScopeConfig = Field(
        default_factory=TenantConversationScopeConfig
    )
    capabilities: dict[str, TenantCapabilityConfig] = Field(default_factory=dict)
    post_call_transcript: TenantPostCallTranscriptConfig | None = None
    voice: TenantVoiceConfig = Field(default_factory=TenantVoiceConfig)

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_locales(cls, value):
        if isinstance(value, dict) and "supported_locales" not in value:
            value = dict(value)
            value["supported_locales"] = [
                value.get("locale") or value.get("default_language")
            ]
        return value

    @field_validator("tenant_id", "name")
    @classmethod
    def validate_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError(f"unknown IANA timezone: {value}") from exc
        return value

    @field_validator("supported_locales")
    @classmethod
    def validate_supported_locales(cls, value: list[str]) -> list[str]:
        if not value or any(not locale.strip() for locale in value):
            raise ValueError("supported_locales must contain at least one non-empty locale")
        if len(value) != len(set(value)):
            raise ValueError("supported_locales must not contain duplicates")
        return value

    @model_validator(mode="after")
    def validate_default_locale(self):
        default_locale = self.locale or self.default_language
        if default_locale not in self.supported_locales:
            raise ValueError("default locale must be included in supported_locales")
        return self

    @model_validator(mode="after")
    def validate_availability_configuration(self):
        capability = self.capabilities.get("reservation.check_availability")
        enabled = bool(capability and capability.enabled)
        if self.features.availability_check != enabled:
            raise ValueError(
                "features.availability_check must match reservation.check_availability"
            )
        if not enabled:
            return self
        if capability.provider != "google_sheets":
            raise ValueError("availability checking requires the google_sheets provider")
        config = TenantAvailabilityConfig.model_validate(capability.config)
        inventory = {
            room_type.code: room_type.inventory_count
            for room_type in self.business_info.room_types
        }
        if set(config.room_type_columns) != set(inventory):
            raise ValueError(
                "availability room_type_columns must match declared room type codes"
            )
        for room_type, column_range in config.room_type_columns.items():
            start, end = spreadsheet_column_span(column_range)
            if end - start + 1 != inventory[room_type]:
                raise ValueError(
                    f"availability range {column_range} width does not match "
                    f"{room_type} inventory count {inventory[room_type]}"
                )
        return self

    @property
    def default_locale(self) -> str:
        return self.locale or self.default_language

    @property
    def availability_config(self) -> TenantAvailabilityConfig | None:
        capability = self.capabilities.get("reservation.check_availability")
        if not capability or not capability.enabled:
            return None
        return TenantAvailabilityConfig.model_validate(capability.config)
