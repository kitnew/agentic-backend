import os
import uuid
from pathlib import Path

from app.voice.errors import VoiceTTSProviderError
from app.voice.schemas import SynthesizedAudioResult


CONTENT_TYPE_EXTENSIONS = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mp4": ".m4a",
    "audio/m4a": ".m4a",
    "audio/aac": ".aac",
    "audio/flac": ".flac",
}


def get_voice_audio_storage_dir() -> Path:
    return Path(os.getenv("VOICE_AUDIO_STORAGE_DIR", "var/voice-audio"))


def get_voice_audio_public_base_url() -> str:
    return os.getenv("VOICE_AUDIO_PUBLIC_BASE_URL", "/api/v1/voice/audio")


class LocalVoiceAudioStorage:
    def __init__(
        self,
        storage_dir: Path | None = None,
        public_base_url: str | None = None,
    ):
        self.storage_dir = storage_dir or get_voice_audio_storage_dir()
        self.public_base_url = (public_base_url or get_voice_audio_public_base_url()).rstrip("/")

    def save(
        self,
        *,
        tenant_id: str,
        conversation_id: str,
        audio: SynthesizedAudioResult,
    ) -> SynthesizedAudioResult:
        if audio.audio_url:
            return audio

        if not audio.audio_bytes:
            raise VoiceTTSProviderError("TTS provider did not return audio bytes")

        self.storage_dir.mkdir(parents=True, exist_ok=True)
        extension = CONTENT_TYPE_EXTENSIONS.get(audio.content_type, ".bin")
        filename = f"{uuid.uuid4().hex}{extension}"
        path = self.storage_dir / filename
        path.write_bytes(audio.audio_bytes)

        return audio.model_copy(
            update={
                "audio_url": f"{self.public_base_url}/{filename}",
                "audio_bytes": None,
                "metadata": {
                    **audio.metadata,
                    "storage": "local",
                    "tenant_id": tenant_id,
                    "conversation_id": conversation_id,
                    "filename": filename,
                },
            }
        )
