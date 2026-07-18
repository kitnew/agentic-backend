from app.tenants.schemas import TenantVoiceConfig
from app.voice.errors import VoiceValidationError
from app.voice.schemas import AudioInput


def normalize_content_type(content_type: str | None) -> str | None:
    if not content_type:
        return None
    return content_type.split(";", 1)[0].strip().lower()


def validate_audio_input(
    audio: AudioInput | None,
    *,
    config: TenantVoiceConfig,
) -> AudioInput:
    if audio is None:
        raise VoiceValidationError("audio_file is required")

    if audio.size_bytes <= 0 or not audio.data:
        raise VoiceValidationError("audio_file must not be empty")

    if audio.size_bytes > config.max_file_size_bytes:
        raise VoiceValidationError(
            f"audio_file exceeds the maximum size of {config.max_file_size_bytes} bytes"
        )

    content_type = normalize_content_type(audio.content_type)
    supported_content_types = {
        normalize_content_type(item)
        for item in config.supported_content_types
        if normalize_content_type(item)
    }
    if content_type not in supported_content_types:
        raise VoiceValidationError(
            f"Unsupported audio content type: {audio.content_type or 'unknown'}"
        )

    return audio.model_copy(update={"content_type": content_type})
