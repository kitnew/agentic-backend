from typing import Protocol

from app.tenants.schemas import TenantVoiceSTTConfig
from app.voice.schemas import AudioInput, TranscriptResult


class STTProvider(Protocol):
    provider_name: str

    def transcribe(
        self,
        audio: AudioInput,
        *,
        config: TenantVoiceSTTConfig,
    ) -> TranscriptResult:
        pass
