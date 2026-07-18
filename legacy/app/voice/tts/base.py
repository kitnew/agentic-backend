from typing import Protocol

from app.tenants.schemas import TenantVoiceTTSConfig
from app.voice.schemas import SynthesizedAudioResult


class TTSProvider(Protocol):
    provider_name: str

    def synthesize(
        self,
        text: str,
        *,
        config: TenantVoiceTTSConfig,
    ) -> SynthesizedAudioResult:
        pass
