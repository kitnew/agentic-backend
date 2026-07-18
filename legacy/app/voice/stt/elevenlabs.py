import os
from typing import Any

import requests

from app.tenants.schemas import TenantVoiceSTTConfig
from app.voice.errors import VoiceProviderConfigurationError, VoiceSTTProviderError
from app.voice.schemas import AudioInput, TranscriptResult


class ElevenLabsSTTProvider:
    provider_name = "elevenlabs"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = "https://api.elevenlabs.io/v1",
        timeout_seconds: int = 120,
    ):
        self.api_key = api_key or os.getenv("ELEVENLABS_API_KEY")
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def transcribe(
        self,
        audio: AudioInput,
        *,
        config: TenantVoiceSTTConfig,
    ) -> TranscriptResult:
        if not self.api_key:
            raise VoiceProviderConfigurationError("ELEVENLABS_API_KEY must be configured")

        form_data: list[tuple[str, str]] = [("model_id", config.model)]
        if config.language:
            form_data.append(("language_code", config.language))
        for keyterm in config.keyterms:
            form_data.append(("keyterms", keyterm))

        files = {
            "file": (
                audio.filename or "audio",
                audio.data,
                audio.content_type or "application/octet-stream",
            )
        }

        try:
            response = requests.post(
                f"{self.base_url}/speech-to-text",
                headers={"xi-api-key": self.api_key},
                data=form_data,
                files=files,
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise VoiceSTTProviderError("STT provider request failed") from exc

        if response.status_code >= 400:
            raise VoiceSTTProviderError(
                f"STT provider request failed with status {response.status_code}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise VoiceSTTProviderError("STT provider returned an invalid response") from exc

        text = self._extract_text(payload)
        words = payload.get("words") or []
        language = payload.get("language_code")
        audio_duration_ms = self._estimate_duration_ms(words)

        return TranscriptResult(
            provider=self.provider_name,
            text=text,
            language=language,
            audio_duration_ms=audio_duration_ms,
            metadata={
                "model": config.model,
                "language_probability": payload.get("language_probability"),
                "word_count": len(words) if isinstance(words, list) else None,
                "request_id": response.headers.get("request-id")
                or response.headers.get("x-request-id"),
            },
        )

    def _extract_text(self, payload: dict[str, Any]) -> str:
        text = payload.get("text")
        if isinstance(text, str):
            return text

        transcripts = payload.get("transcripts")
        if isinstance(transcripts, dict):
            parts = [
                transcript.get("text", "")
                for transcript in transcripts.values()
                if isinstance(transcript, dict)
            ]
            return "\n".join(part for part in parts if part)

        return ""

    def _estimate_duration_ms(self, words: Any) -> int | None:
        if not isinstance(words, list):
            return None

        end_times = [
            word.get("end")
            for word in words
            if isinstance(word, dict) and isinstance(word.get("end"), int | float)
        ]
        if not end_times:
            return None

        return int(max(end_times) * 1000)
